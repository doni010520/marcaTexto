import os
import json
from fastapi import FastAPI, HTTPException, Header
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel
import logging

# Configuração do logging para ver as mensagens no Easypanel
logging.basicConfig(level=logging.INFO)

# --- Configuração ---
logging.info("Iniciando a configuração da aplicação...")

try:
    CREDENTIALS_JSON_STR = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not CREDENTIALS_JSON_STR:
        logging.error("ERRO CRÍTICO: Variável de ambiente GOOGLE_CREDENTIALS_JSON não encontrada.")
        raise ValueError("GOOGLE_CREDENTIALS_JSON não configurada")
    logging.info("Sucesso: Variável GOOGLE_CREDENTIALS_JSON carregada.")
    
    creds_info = json.loads(CREDENTIALS_JSON_STR)
    logging.info("Sucesso: GOOGLE_CREDENTIALS_JSON parseado com sucesso.")

    TOKEN_JSON_STR = os.environ.get("GOOGLE_TOKEN_JSON")
    if not TOKEN_JSON_STR:
        logging.error("ERRO CRÍTICO: Variável de ambiente GOOGLE_TOKEN_JSON não encontrada.")
        raise ValueError("GOOGLE_TOKEN_JSON não configurada")
    logging.info("Sucesso: Variável GOOGLE_TOKEN_JSON carregada.")
    
    token_info = json.loads(TOKEN_JSON_STR)
    logging.info("Sucesso: GOOGLE_TOKEN_JSON parseado com sucesso.")

    API_KEY = os.environ.get("API_KEY")
    if not API_KEY:
        logging.error("ERRO CRÍTICO: Variável de ambiente API_KEY não encontrada.")
        raise ValueError("API_KEY não configurada")
    logging.info("Sucesso: Variável API_KEY carregada.")

except (json.JSONDecodeError, ValueError) as e:
    logging.error(f"ERRO CRÍTICO durante a inicialização: {e}")
    raise

SCOPES = ["https://www.googleapis.com/auth/documents"]

app = FastAPI()

class ProcessRequest(BaseModel):
    documento_fonte_id: str
    documento_destino_id: str

def get_credentials_from_env():
    client_config = creds_info.get('installed', creds_info.get('web'))
    creds = Credentials(
        token=token_info.get('token'),
        refresh_token=token_info.get('refresh_token'),
        token_uri=client_config.get('token_uri'),
        client_id=client_config.get('client_id'),
        client_secret=client_config.get('client_secret'),
        scopes=SCOPES
    )
    if creds and creds.expired and creds.refresh_token:
        logging.info("Token de acesso expirado. A atualizar...")
        creds.refresh(Request())
        logging.info("Token atualizado com sucesso.")
    return creds

def get_red_text(docs_service, document_id):
    document = docs_service.documents().get(documentId=document_id).execute()
    doc_content = document.get("body").get("content")
    texto_vermelho = ""
    for value in doc_content:
        if "paragraph" in value:
            elements = value.get("paragraph").get("elements")
            for elem in elements:
                text_run = elem.get("textRun")
                if text_run and "textStyle" in text_run and "foregroundColor" in text_run["textStyle"]:
                    color_info = text_run["textStyle"]["foregroundColor"].get("color", {}).get("rgbColor", {})
                    if color_info.get("red") == 1 and not color_info.get("green") and not color_info.get("blue"):
                        texto_vermelho += text_run.get("content")
    return texto_vermelho.replace('\n', '') if texto_vermelho else None

def find_text_and_highlight(docs_service, document_id, text_to_find):
    requests = [{
        "replaceAllText": {
            "containsText": {"text": text_to_find, "matchCase": True},
            "replaceText": text_to_find,
            "textStyle": {
                "backgroundColor": {"color": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 0.0}}}
            }
        }
    }]
    docs_service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()

@app.get("/")
async def health_check():
    return {"status": "ok"}

@app.post("/processar")
async def processar_documento(req: ProcessRequest, x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Chave de API inválida.")
    try:
        creds = get_credentials_from_env()
        service = build("docs", "v1", credentials=creds)
        texto_para_destacar = get_red_text(service, req.documento_fonte_id)
        if not texto_para_destacar:
            return {"status": "sucesso", "detail": "Nenhum texto em vermelho foi encontrado."}
        find_text_and_highlight(service, req.documento_destino_id, texto_para_destacar)
        return {"status": "sucesso", "detail": f"Texto '{texto_para_destacar}' destacado com sucesso."}
    except HttpError as e:
        error_details = json.loads(e.content).get('error', {})
        logging.error(f"Erro na API do Google: {error_details}")
        raise HTTPException(
            status_code=400, 
            detail=f"Erro na API do Google: {error_details.get('message', 'Erro desconhecido')}. Verifique se o ID do documento é de um Google Doc nativo."
        )
    except Exception as e:
        logging.error(f"Erro interno não esperado: {e}")
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro interno: {str(e)}")

