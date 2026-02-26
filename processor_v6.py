import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SQL_PROMPT_TEMPLATE = """
You are an expert Microsoft T-SQL server query generator. Your task is to convert natural language to SQL and return safe analytical responses. Only generate SELECT queries.
Strictly do NOT generate anything beyond the SQL query, no logs, explanations, or similar.
Below is the database schema:

CREATE DATABASE EmployeeDB;
GO

USE EmployeeDB;
GO

CREATE TABLE Departments (
    DeptID INT IDENTITY(1,1) PRIMARY KEY,
    DeptName VARCHAR(50) NOT NULL UNIQUE,
    Location VARCHAR(50) NOT NULL
);
GO

-- Create Employees table
CREATE TABLE Employees (
    EmpID INT IDENTITY(1,1) PRIMARY KEY,
    FirstName VARCHAR(50) NOT NULL,
    LastName VARCHAR(50) NOT NULL,
    BirthDate DATE NOT NULL,
    HireDate DATE NOT NULL,
    JobTitle VARCHAR(50) NOT NULL,
    Salary DECIMAL(10,2) NOT NULL,
    DeptID INT NOT NULL,
    FOREIGN KEY (DeptID) REFERENCES Departments(DeptID)
);
GO

INSERT INTO Departments (DeptName, Location) VALUES
('IT', 'New York'),
('HR', 'Chicago'),
('Finance', 'Dallas'),
('Marketing', 'Boston');

INSERT INTO Employees (FirstName, LastName, BirthDate, HireDate, JobTitle, Salary, DeptID) VALUES
('John', 'Doe', '1985-03-15', '2015-06-01', 'Software Engineer', 85000.00, 1),
('Jane', 'Smith', '1990-07-22', '2018-01-10', 'HR Manager', 75000.00, 2),
('Mike', 'Johnson', '1988-11-05', '2016-09-15', 'Accountant', 65000.00, 3),
('Lisa', 'Brown', '1992-02-10', '2019-03-20', 'Marketing Specialist', 60000.00, 4);
GO   
"""

_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_LATEST_RESULT_FILEPATH = None

TABLE_NAMES = {"employees", "departments"}
PERSONAL_INFO_COLUMNS = {"firstname", "lastname", "birthdate"}
SENSITIVE_COLUMNS_FOR_ANALYST = PERSONAL_INFO_COLUMNS
ALL_EMPLOYEE_COLUMNS = {
    "empid",
    "firstname",
    "lastname",
    "birthdate",
    "hiredate",
    "jobtitle",
    "salary",
    "deptid",
}

ANALYST_BLOCKED_KEYWORDS = {
    "first name",
    "firstname",
    "last name",
    "lastname",
    "birth date",
    "birthdate",
    "personal info",
    "personal information",
    "employee name",
}
USER_REQUIRED_KEYWORDS = {"my", "mine", "me", "myself"}
USER_BLOCKED_KEYWORDS = {
    "all employees",
    "everyone",
    "other employee",
    "other employees",
    "entire company",
    "team members",
}


def get_latest_result_filepath():
    return _LATEST_RESULT_FILEPATH


def _save_current_result(user_query: str, generated_sql: str, final_response: str):
    global _LATEST_RESULT_FILEPATH
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = _RESULTS_DIR / f"results_{ts}.json"

    payload = {
        "timestamp": ts,
        "query": user_query,
        "intermediate_output": generated_sql,
        "final_response": final_response,
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _LATEST_RESULT_FILEPATH = str(result_path)
    return _LATEST_RESULT_FILEPATH


def _tokenize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def validate_question_for_role(
    prompt: str, role: str, current_user: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    clean_prompt = _tokenize_text(prompt)
    role_name = (role or "user").strip().lower()

    if role_name == "admin":
        return None

    if role_name == "analyst":
        if _contains_any(clean_prompt, ANALYST_BLOCKED_KEYWORDS):
            return "Analyst role cannot request employee personal information."
        return None

    if role_name == "user":
        if _contains_any(clean_prompt, USER_BLOCKED_KEYWORDS):
            return "User role can only ask for their own records."
        if not _contains_any(clean_prompt, USER_REQUIRED_KEYWORDS):
            return "User role questions must be framed as self-data requests (for example: 'my details')."
        if not current_user or not current_user.get("employee_code"):
            return "User identity is missing for access validation."
        return None

    return "Unsupported user role."


def _extract_identifiers(sql_text: str) -> set:
    return {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql_text or "")}


def validate_generated_sql_for_role(
    generated_sql: str, role: str, current_user: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    sql_text = (generated_sql or "").strip()
    if not sql_text:
        return "No SQL was generated."

    if not sql_text.lower().startswith("select"):
        return "Only SELECT queries are allowed."

    identifiers = _extract_identifiers(sql_text)
    role_name = (role or "user").strip().lower()

    if role_name == "admin":
        return None

    if role_name == "analyst":
        if identifiers.intersection(SENSITIVE_COLUMNS_FOR_ANALYST):
            return "Generated SQL includes personal employee columns not allowed for analyst role."
        return None

    if role_name == "user":
        lowered = sql_text.lower()
        if not identifiers.intersection(TABLE_NAMES):
            return None
        if identifiers.intersection(ALL_EMPLOYEE_COLUMNS - {"empid"}):
            # Keep user requests constrained to row-level ownership checks for now.
            pass
        employee_code = (current_user or {}).get("employee_code", "")
        digits = "".join(ch for ch in str(employee_code) if ch.isdigit())
        if not digits:
            return "User identity employee code is invalid for SQL validation."
        if " where " not in lowered:
            return "User query must include row-level filtering."
        if "empid" not in lowered:
            return "User query must filter by employee id."
        if digits not in lowered:
            return "Generated SQL is not filtered to the requesting user."
        return None

    return "Unsupported user role for SQL validation."


def format_sql_result(sql_result: Any) -> str:
    if sql_result is None:
        return "Query generated. No SQL result payload was provided."

    if isinstance(sql_result, dict):
        parts = []
        for key, value in sql_result.items():
            label = str(key).replace("_", " ").strip().capitalize()
            parts.append(f"{label} is {value}")
        return " and ".join(parts) + "."

    if isinstance(sql_result, list):
        if not sql_result:
            return "No records found."
        if isinstance(sql_result[0], dict):
            lines: List[str] = []
            for idx, row in enumerate(sql_result[:5], start=1):
                row_parts = []
                for key, value in row.items():
                    label = str(key).replace("_", " ").strip().capitalize()
                    row_parts.append(f"{label} is {value}")
                lines.append(f"Record {idx}: " + " and ".join(row_parts) + ".")
            return " ".join(lines)
        return ", ".join(str(item) for item in sql_result[:10])

    return str(sql_result)


def process_query(prompt, sql_query, sql_result, sql_model, user_context=None):
    if sql_model is None:
        raise RuntimeError("SQL model is not loaded")

    user_query = (prompt or "").strip()
    if not user_query:
        yield "Empty query received."
        return

    role = (user_context or {}).get("role", "user")

    role_validation_error = validate_question_for_role(user_query, role, user_context)
    if role_validation_error:
        yield f"Access denied: {role_validation_error}"
        yield "---EOR---"
        return

    stage_1_prompt = (SQL_PROMPT_TEMPLATE + "\n" + user_query).strip()
    yield "[LMSTUDIO] Generating intermediate response..."
    try:
        generated_sql = (sql_query or "").strip() if sql_query else sql_model.generate(stage_1_prompt)
    except Exception as e:
        final_response = f"Model generation failed: {e}"
        _save_current_result(user_query, "", final_response)
        yield final_response
        yield "---EOR---"
        return

    if generated_sql and generated_sql.strip():
        yield f"[LMSTUDIO] Intermediate output:\n{generated_sql.strip()}"

    sql_validation_error = validate_generated_sql_for_role(generated_sql, role, user_context)
    if sql_validation_error:
        final_response = f"Access denied after SQL validation: {sql_validation_error}"
        _save_current_result(user_query, generated_sql or "", final_response)
        yield final_response
        yield "---EOR---"
        return

    try:
        final_response = format_sql_result(sql_result)
    except Exception as e:
        final_response = f"Result formatting failed: {e}"
    if final_response and final_response.strip():
        _save_current_result(user_query, generated_sql or "", final_response.strip())
        yield final_response.strip()
    else:
        _save_current_result(user_query, generated_sql or "", "No response generated.")
        yield "No response generated."

    yield "---EOR---"


def get_role_based_system_prompt(role: str):

    base_prompt = """

    You are an AI system that converts natural language to SQL and returns safe analytical responses.
    Only generate SELECT queries.
    """

    role_variations = {
        "admin": "\nUser role: ADMIN. Full analytical reasoning allowed.",
        "analyst": "\nUser role: ANALYST. Exclude personal employee information.",
        "user": "\nUser role: USER. Restrict results to the requesting employee record."
    }

    return base_prompt + role_variations.get(role, "")
