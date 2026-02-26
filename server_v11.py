# this server module sends queue positions to users and updates them in real-time.
# use this module to link with other modules and use the accompanied index_v11.py file (index file on system to be updated with the merged changes)

import asyncio
import threading
import logging
import os
import json
from collections import deque
from itertools import count
from typing import Iterable
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles

from models_v1 import load_sql_model
from processor_v6 import process_query, get_latest_result_filepath
from utils_v2 import check_gpu
from auth_v1 import (
    authenticate_user,
    create_access_token,
    get_current_user,
    register_user,
    ensure_auth_tables,
)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename = f'logs/app_{timestamp}.log', level=logging.DEBUG, filemode = 'a', format="%(asctime)s - %(levelname)s - %(message)s")

sql_model = None
stop_event = threading.Event()

class QueryRequest(BaseModel):
    prompt: str = Field(..., description="User Query")

llm_queue = asyncio.Queue()
requests_by_id = {}
waiting_request_ids = deque()
current_request_id = None
request_id_counter = count(1)
queue_state_lock = asyncio.Lock()


def _queue_chunk(message: str) -> str:
    return f"[QUEUE] {message}\n"


def _sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _parse_queue_payload(chunk: str) -> dict:
    payload = chunk.replace("[QUEUE]", "", 1).strip()
    parts = payload.split()
    data = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        data[key] = value
    return data


async def _emit_queue_positions():
    # Build updates while holding the lock, then emit outside the lock.
    updates = []
    async with queue_state_lock:
        has_current = current_request_id is not None
        for idx, request_id in enumerate(waiting_request_ids, start=1):
            request_state = requests_by_id.get(request_id)
            if not request_state or request_state.get("disconnected"):
                continue
            position = (1 if has_current else 0) + idx
            updates.append(
                (request_state["client_q"], _queue_chunk(f"position={position} status=queued"))
            )

    for client_q, message in updates:
        await client_q.put(message)

@asynccontextmanager
async def lifespan(app: FastAPI):

    asyncio.create_task(llm_worker())
    logging.info("[SERVER] Worker created")

    global sql_model
    logging.info("[SERVER] Starting server...")
    print("\n[SERVER] Server started")
    check_gpu()
    try:
        ensure_auth_tables()
    except Exception as e:
        logging.error(f"[SERVER] Auth table initialization failed: {e}")

    print("\n[SERVER] Loading models")
    sql_model = load_sql_model()
    print("\n[SERVER] Models loaded and ready")
    logging.info("[SERVER] Models loaded and ready")

    yield

    print("\n[SERVER] Shutting down...")
    logging.info("[SERVER] Shutting down...")
    if sql_model:
        sql_model.close()

app = FastAPI(lifespan=lifespan)

async def llm_worker():
    global current_request_id
    while True:
        request_id = await llm_queue.get()
        client_q = None
        prompt = None

        try:
            async with queue_state_lock:
                request_state = requests_by_id.get(request_id)
                if not request_state:
                    # Stale request (e.g. client disconnected while waiting).
                    if request_id in waiting_request_ids:
                        waiting_request_ids.remove(request_id)
                    continue

                prompt = request_state["prompt"]
                client_q = request_state["client_q"]

                if waiting_request_ids and waiting_request_ids[0] == request_id:
                    waiting_request_ids.popleft()
                elif request_id in waiting_request_ids:
                    waiting_request_ids.remove(request_id)

                current_request_id = request_id

            if client_q:
                await client_q.put(_queue_chunk("position=1 status=processing"))

            await _emit_queue_positions()

            # Reset model state only when worker is about to process this request.
            # sql_model.reset()

            user_context = request_state.get("user_context") or {}
            result = process_query(prompt, None, None, sql_model, user_context=user_context)
            chunks: Iterable

            # process_query may return a single string or an iterable of chunks.
            if isinstance(result, str):
                chunks = [result]
            else:
                chunks = result

            saw_eor = False
            chunks_iter = iter(chunks)
            _end_of_chunks = object()
            while True:
                # Use a sentinel so StopIteration is not raised through asyncio Future.
                chunk = await asyncio.to_thread(next, chunks_iter, _end_of_chunks)
                if chunk is _end_of_chunks:
                    break

                if chunk is None:
                    continue
                outgoing = chunk
                if isinstance(chunk, str) and not chunk.endswith("\n"):
                    # Ensure chunk boundaries are line-delimited for real-time client rendering.
                    outgoing = f"{chunk}\n"

                await client_q.put(outgoing)
                if isinstance(chunk, str) and "---EOR---" in chunk:
                    saw_eor = True
                    break

            if not saw_eor:
                await client_q.put("\n---EOR---")

            if client_q:
                await client_q.put(None)
        
        except Exception as e:
            print(f"Error in worker during request '{request_id}' ({prompt}): {e}")
            logging.error(f"Error in worker during request '{request_id}' ({prompt}): {e}")
            err_chunk = f"\n[SERVER] Error: {str(e)}\n---EOR---"
            if client_q:
                await client_q.put(err_chunk)
                await client_q.put(None)
        finally:
            async with queue_state_lock:
                if current_request_id == request_id:
                    current_request_id = None
                requests_by_id.pop(request_id, None)

            await _emit_queue_positions()
            logging.info(f"[SERVER] Worker completed work for request_id={request_id}")
            llm_queue.task_done()


# ENDPOINTS

@app.get("/query")
async def generate(req: QueryRequest = Depends(), current_user: dict = Depends(get_current_user)):
    client_q = asyncio.Queue()

    prompt = req.prompt.strip()

    print(f"\nPrompt received: {prompt}")
    if not prompt:
        print("\n[SERVER] Empty prompt")
        raise HTTPException(status_code=400, detail="Empty prompt")

    logging.info(f"[SERVER] Received query: {prompt}")
    request_id = next(request_id_counter)

    async with queue_state_lock:
        requests_by_id[request_id] = {
            "prompt": prompt,
            "client_q": client_q,
            "user_context": current_user,
            "disconnected": False,
        }
        waiting_request_ids.append(request_id)
        current_exists = current_request_id is not None
        position = (1 if current_exists else 0) + len(waiting_request_ids)

    await llm_queue.put(request_id)
    await client_q.put(_queue_chunk(f"request_id={request_id} position={position} status=queued"))
    await _emit_queue_positions()
    logging.info(f"[SERVER] Added request_id={request_id} to queue at position={position}")

    async def stream_to_client():
        sent_end = False
        try:
            while True:
                chunk = await client_q.get()
                if chunk is None:
                    if not sent_end:
                        sent_end = True
                        yield _sse_event("end", {"status": "completed"})
                    break
                logging.info(f"[SERVER] Chunk from client queue: {chunk}")

                if isinstance(chunk, str) and chunk.startswith("[QUEUE]"):
                    yield _sse_event("queue", _parse_queue_payload(chunk))
                    continue

                if isinstance(chunk, str) and "---EOR---" in chunk:
                    clean = chunk.replace("---EOR---", "")
                    if clean.strip():
                        yield _sse_event("chunk", {"text": clean})
                    if not sent_end:
                        sent_end = True
                        yield _sse_event("end", {"status": "completed"})
                    continue

                text = chunk if isinstance(chunk, str) else str(chunk)
                if text.strip():
                    yield _sse_event("chunk", {"text": text})
        except Exception as e:
            print(f"Error during streaming: {e}")
            logging.error(f"Error during streaming: {e}")
            yield _sse_event("server_error", {"message": str(e)})
        finally:
            removed_waiting = False
            async with queue_state_lock:
                request_state = requests_by_id.get(request_id)
                if request_state:
                    request_state["disconnected"] = True

                if current_request_id != request_id and request_id in waiting_request_ids:
                    waiting_request_ids.remove(request_id)
                    requests_by_id.pop(request_id, None)
                    removed_waiting = True

            if removed_waiting:
                await _emit_queue_positions()
    
    logging.info("[SERVER] Streaming to user")
    return StreamingResponse(
        stream_to_client(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/queue-position")
async def queue_position(request_id: int):
    async with queue_state_lock:
        if current_request_id == request_id:
            return {"request_id": request_id, "position": 1, "status": "processing"}

        waiting_list = list(waiting_request_ids)
        if request_id in waiting_list:
            idx = waiting_list.index(request_id)
            position = (1 if current_request_id is not None else 0) + idx + 1
            return {"request_id": request_id, "position": position, "status": "queued"}

        if request_id in requests_by_id:
            return {"request_id": request_id, "position": None, "status": "finalizing"}

    return {"request_id": request_id, "position": None, "status": "completed_or_unknown"}


@app.get("/download")
def returnFile():
    try:
        filepath = get_latest_result_filepath()
        if filepath and os.path.exists(filepath):
            print(f"[SERVER] Returning FileResponse on {filepath}")
            logging.info(f"[SERVER] Returning FileResponse on {filepath}")

            headers = {
                f'Content-Disposition': f'attachment; filename="{os.path.basename(filepath)}"'
            }

            return FileResponse(
                path = filepath,
                headers=headers,
                media_type = 'application/octet-stream'
            )
        
        else:
            print(f"[SERVER] File not found:")
            logging.info(f"[SERVER] File not found:")
            raise HTTPException(status_code=404, detail="File not found")
    
    except Exception as e:
        print(f"[SERVER] Error during FileResponse: {e}")
        logging.info(f"[SERVER] Error during FileResponse: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="Download failed")


@app.post("/stop")
def stop():
    stop_event.set()
    print("\n[SERVER] Stop signal received")
    logging.info("[SERVER] Stop signal received")
    return {"status": "stopped"}


@app.post("/resume")
def resume():
    stop_event.clear()
    print("\n[SERVER] Resume signal received")
    logging.info("[SERVER] Resume signal received")
    return {"status": "running"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class LocalLoginRequest(BaseModel):
    employee_code: str
    password: str


@app.post("/login-local")
def login_local(data: LocalLoginRequest):
    try:
        user = authenticate_user(data.employee_code, data.password)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[SERVER] Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user)

    return {"access_token": token}


class RegisterRequest(BaseModel):
    name: str
    employee_code: str
    password: str


@app.post("/register")
def register(data: RegisterRequest):
    try:
        created = register_user(data.name, data.employee_code, data.password)
        return {
            "message": "Registration successful",
            "employee_code": created["employee_code"],
            "role": created["role"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[SERVER] Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

app.mount("/", StaticFiles(directory = "static", html = True), name = "static")
if __name__ == "__main__":

    uvicorn.run(
        "server_v11:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )
