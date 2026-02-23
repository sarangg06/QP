This is a readme file for the BACS Query Processor project (BACSQP).

This readme should serve the reader as a complete technical guide for using the BACSQP, including code information, setup, and usage.

---

## **What is BACSQP & Who is it for?**

The BACS Query Processor is a web-app developed for users to access information related to Biometric Access Controllers installed across the campus. These controllers are installed for access authorization in various work areas in the campus.

The main goal of the web-app is to convert natural-language questions into SQL queries using a local Large Language Model (LLM), execute those queries against a Microsoft SQL Server database, and return a single human-readable response.

It can be used by authorized employees and non-employees who may require such information for work-related needs.

---

## **Core Features**

1. Natural language queries are processed to provide SQL based responses.
2. LLMs are used locally (GGUF) with FastAPI to give efficient results.
3. User queries are validated for domain relevancy and malicious/unrelated queries are blocked from execution.
4. Generated queries are checked syntactically and semantically.
5. Human readable plain text/Markdown responses are returned.
6. Large results are returned as downloadable Excel data sheets.

---

## Technology Stack

### Frontend

1. HTML5 - Form elements and reliable page structure.
2. JavaScript - Functionality, validation, client-side scripting. 
3. CSS - Clean and neat UI/UX.

### Backend

1. Server is managed using **FastAPI** and peripherals:
    1. Server management - Uvicorn 
    2. Data validation - Pydantic (BaseModel)
    3. Request routing - HTTP routes
    
    It communicates between frontend interface and backend processor.
    
2. Processor is developed in **Python**:
    1. LLM handling - Llama_cpp
    2. SQL generation - Llama 3.2 8b Custom FTM GGUF
    3. SQL handling and execution - Pyodbc
    4. Response generation - DeepSeek R1 Distill GGUF
    5. Large result handling - Pandas
    6. Other utils - OS, RE
3. Data is stored in **SQL**

---

## Modules

### server_fastapi_vX.py

This is the main module used for running and managing the server. It uses FastAPI and Uvicorn to manage the server.

Key functions:

1. Managing the server - Starting, ending, handling errors.
2. Routing requests - `GET /`, `GET /query`, `POST /stop`
3. Loading models - Using functions from utils_vX.py
4. Calling other modules - `processor_vX.py`, `models_vX.py`, `utils_vX.py` 
5. Streaming requests - Using `StreamingResponse` and `FileResponse` 

### processor_v3.py

This module is called by the server module. It processes the queries and streams the response back to the server module.

Key functions:

1. Validating questions - Checked for domain relevancy.
2. Processing queries - Processing user query using `Llama 3.1 8b IFTM` model.
3. Executing queries - Executing validated queries using `pyodbc`.
4. Processing results - Processing results using `DeepSeek R1 Distill` model and responding to user.
5. Handling errors - Handling errors that occur during the whole processing.

---

## Setup and Access Instructions

1. Starting from scratch, run `pip install -r requirements.txt` in any CLI (Git Bash is recommended).
2. Once the dependencies are installed, look for `server_fastapi_vX.py` file.
In that file, check if the `verbose` are set to True.
Set the following environment variables to their respective values:
SQL_MODEL_PATH, RESPONSE_MODEL_PATH, RESULT_FILE_DIR, CONNECTION_STRING (SQL database connection string).
3. Run the python file using `python server_fastapi_vX.py` .
You should see the servers starting, the models being loaded into the memory, a “*Models loaded and ready* ” text on CLI, and finally a line saying 
“`*Server running on 127.0.0.1:8000`“.*
4. Open this address in browser and you should see the interface. If not visible, check if there are *index.html, styles.css, purify.min.js, and marked.min.js* files in public folder in current working directory. These files are loaded during the starting of the server.
5. Once the server is running and interface is loaded, there should be a “`*GET /`”* request on CLI with status code as `200 OK`.
6. Then you can enter any test query and click on process. This should make following request:
“`*GET /query?prompt=query%20you%20entered%3F*`” 
The server will keep waiting for requests to process unless Internal Server Errors occur or the server is explicitly shut down.
7. Then the processing should happen with following prints to be considered as milestones:
    1. “***Question is relevant*** ” - This means that the user question is relevant to our domain and database.
    2. “***LLM processing time info - 1*** ” - This means the LLM has processed the question and generated a SQL query, which is being executed and will be sent to response model.
    3. “***Query results*** ” - If the query was accurate and returned some non-empty results, then they should be printed on the CLI. The results can also be empty (*NoData*), may contain error (*ERROR*), or may be large (LargeResult) which would be printed in the CLI.
    4. “***Normal results, responding to user*** ” - This means the results are normal and are being processed by the response model.
    5. “***LLM processing time info - 2*** ” - It shows that the response model has successfully converted the results into human-readable response.
    6. “***All queries executed*** ” - It means there are no requests remaining to process.
8. This should return a single response which is streamed from processor to frontend using StreamingResponse functionality of FastAPI, which has its own data format.
The last response sent must be a “—-EOR—- & complete=True” message.
9. If the result is large, large=True message is also sent which activates a download button (connected to /download) route for downloading the results.
10. For shutting down the server, press Ctrl + C once and wait for background activities to stop and for server to shut down completely.

---

## Currently Known Limitations

The project has a few limitations that noticeably affect its functionality. Limitations may be errors, malfunctions, abnormal behaviors, and similar.

### Processing Latency

Currently, the latency has been reduced down to ~17 seconds per model, largely depending on query complexity and result length.
On average, 

1. SQL model may take 15-20 seconds to generate a complex SQL query from user’s natural language query.
2. Response model may take 15-20 seconds to generate a human-readable response from the results.

### Hallucinations

Although extremely rare, some models may hallucinate during response generation for empty results. Hallucinations have not been seen with latest used models but have been seen on other models. Thus, only the recommended models should be used to avoid incorrect results.

### Stop Request Issue

The query processor may malfunction if a stop request is received and may reject requests after that with status code 400 Bad Request.
This may be because of improper `POST /stop` request handling and should be fixed with the next update.

### One Request at a Time

The server is able to handle multiple requests at a time, but the processor can only process one query at a time (user query to response).
This is because both models occupy whole 12 GB vRam of NVIDIA RTX 3070 and can only process one query at a time.

---
