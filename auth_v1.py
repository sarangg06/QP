import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import bcrypt
import jwt
import pyodbc
from fastapi import HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer


SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-this-in-production")
ALGORITHM = os.getenv("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("AUTH_TOKEN_EXPIRE_MINUTES", "60"))
MSSQL_CONN_STR = os.getenv(
    "MSSQL_CONN_STR",
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=EmployeeDB;Trusted_Connection=yes;",
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login-local")


def _connect():
    try:
        return pyodbc.connect(MSSQL_CONN_STR, timeout=5)
    except Exception as e:
        raise RuntimeError(f"Database connection failed: {e}") from e


def _employee_code_to_emp_id(employee_code: str) -> Optional[int]:
    if not employee_code:
        return None
    digits = "".join(ch for ch in employee_code if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _determine_user_role(employee_code: str) -> str:
    code = (employee_code or "").strip().lower()
    admin_codes = {
        item.strip().lower()
        for item in os.getenv("ADMIN_EMPLOYEE_CODES", "").split(",")
        if item.strip()
    }
    analyst_codes = {
        item.strip().lower()
        for item in os.getenv("ANALYST_EMPLOYEE_CODES", "").split(",")
        if item.strip()
    }
    if code in admin_codes:
        return "admin"
    if code in analyst_codes:
        return "analyst"
    return "user"


def ensure_auth_tables():
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            IF OBJECT_ID('dbo.AppUsers', 'U') IS NULL
            BEGIN
                CREATE TABLE dbo.AppUsers (
                    UserID INT IDENTITY(1,1) PRIMARY KEY,
                    Name VARCHAR(100) NOT NULL,
                    EmployeeCode VARCHAR(50) NOT NULL UNIQUE,
                    PasswordHash VARCHAR(255) NOT NULL,
                    UserRole VARCHAR(20) NOT NULL CHECK (UserRole IN ('user','analyst','admin')),
                    CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
                );
            END
            """
        )
        conn.commit()
    finally:
        conn.close()


def employee_code_exists(employee_code: str) -> bool:
    emp_id = _employee_code_to_emp_id(employee_code)
    if emp_id is None:
        return False

    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM dbo.Employees WHERE EmpID = ?", emp_id)
        return cursor.fetchone() is not None
    finally:
        conn.close()


def register_user(name: str, employee_code: str, password: str) -> Dict[str, Any]:
    safe_name = (name or "").strip()
    safe_code = (employee_code or "").strip()
    if not safe_name or not safe_code or not password:
        raise HTTPException(status_code=400, detail="Name, employee code, and password are required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    if not employee_code_exists(safe_code):
        raise HTTPException(status_code=400, detail="Invalid employee code")

    ensure_auth_tables()

    role = _determine_user_role(safe_code)
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM dbo.AppUsers WHERE EmployeeCode = ?", safe_code)
        if cursor.fetchone() is not None:
            raise HTTPException(status_code=409, detail="Employee code already registered")

        cursor.execute(
            """
            INSERT INTO dbo.AppUsers (Name, EmployeeCode, PasswordHash, UserRole)
            VALUES (?, ?, ?, ?)
            """,
            safe_name,
            safe_code,
            password_hash,
            role,
        )
        conn.commit()

        return {"name": safe_name, "employee_code": safe_code, "role": role}
    finally:
        conn.close()


def authenticate_user(employee_code: str, password: str) -> Optional[Dict[str, Any]]:
    safe_code = (employee_code or "").strip()
    if not safe_code or not password:
        return None

    ensure_auth_tables()
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT Name, EmployeeCode, PasswordHash, UserRole FROM dbo.AppUsers WHERE EmployeeCode = ?",
            safe_code,
        )
        row = cursor.fetchone()
        if not row:
            return None

        name, code, password_hash, role = row
        if not bcrypt.checkpw(password.encode("utf-8"), str(password_hash).encode("utf-8")):
            return None

        return {"name": name, "employee_code": code, "role": role}
    finally:
        conn.close()


def create_access_token(identity: Dict[str, Any]) -> str:
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": identity.get("employee_code"),
        "name": identity.get("name"),
        "role": identity.get("role"),
        "exp": int(expire_at.timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {
            "employee_code": payload.get("sub"),
            "name": payload.get("name"),
            "role": payload.get("role", "user"),
        }
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=401, detail="Token expired") from e
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e


def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    return decode_access_token(token)
