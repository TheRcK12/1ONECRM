from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_TIMEOUT_SECONDS = 35.0


class OpenAIIntegrationError(RuntimeError):
    """Erro base da integração OpenAI do ONE CRM."""


class OpenAIConfigurationError(OpenAIIntegrationError):
    """A integração não foi configurada corretamente."""


class OpenAIAuthenticationError(OpenAIIntegrationError):
    """A chave informada foi rejeitada pela OpenAI."""


class OpenAIRateLimitError(OpenAIIntegrationError):
    """A OpenAI recusou a chamada por limite ou saldo."""


class OpenAIConnectionError(OpenAIIntegrationError):
    """Não foi possível concluir a comunicação com a OpenAI."""


@dataclass(frozen=True)
class OpenAISettings:
    enabled: bool
    configured: bool
    api_key: str
    model: str
    model_source: str
    endpoint: str
    timeout_seconds: float


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def get_openai_settings(model_override: str | None = None) -> OpenAISettings:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    environment_model = (os.getenv("OPENAI_MODEL") or "").strip()
    override = (model_override or "").strip()
    model = environment_model or override or DEFAULT_OPENAI_MODEL
    model_source = "environment" if environment_model else "database" if override else "default"
    enabled = _env_flag("ONE_CRM_AI_ENABLED", bool(api_key))
    endpoint = (os.getenv("OPENAI_API_URL") or DEFAULT_OPENAI_API_URL).strip()
    try:
        timeout_seconds = float(os.getenv("ONE_CRM_AI_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = min(120.0, max(5.0, timeout_seconds))
    return OpenAISettings(
        enabled=enabled,
        configured=bool(api_key),
        api_key=api_key,
        model=model,
        model_source=model_source,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
    )


def public_openai_status(model_override: str | None = None) -> dict[str, Any]:
    settings = get_openai_settings(model_override)
    return {
        "enabled": settings.enabled,
        "configured": settings.configured,
        "ready": settings.enabled and settings.configured,
        "model": settings.model,
        "model_source": settings.model_source,
        "key_source": "environment" if settings.configured else "missing",
        "endpoint": settings.endpoint,
    }


def _extract_output_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
    return "\n\n".join(texts).strip()


def _error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
    return fallback


def create_openai_response(
    *,
    question: str,
    context: dict[str, Any],
    model_override: str | None = None,
    max_output_tokens: int = 900,
) -> dict[str, Any]:
    settings = get_openai_settings(model_override)
    if not settings.enabled:
        raise OpenAIConfigurationError("A inteligência artificial está desativada no ambiente.")
    if not settings.configured:
        raise OpenAIConfigurationError("OPENAI_API_KEY não foi configurada no Railway.")

    clean_question = (question or "").strip()
    if not clean_question:
        raise ValueError("A pergunta não pode estar vazia.")
    if len(clean_question) > 2_000:
        raise ValueError("A pergunta excede o limite de 2.000 caracteres.")

    instructions = (
        "Você é o ONE Intelligence, assistente operacional do ONE CRM. "
        "Responda sempre em português do Brasil, de forma objetiva, profissional e útil. "
        "Use exclusivamente os dados fornecidos no contexto. Não invente clientes, datas, status, valores ou fatos. "
        "Diferencie claramente fatos registrados de recomendações. "
        "Não revele nem solicite CPF, telefone, e-mail, endereço completo, senha, chave de API ou qualquer segredo. "
        "Não afirme que executou alterações no CRM. Você apenas analisa e sugere ações. "
        "Quando o contexto for insuficiente, diga exatamente qual dado está faltando."
    )
    input_payload = {
        "contexto_one_crm": context,
        "pergunta": clean_question,
    }
    request_payload = {
        "model": settings.model,
        "instructions": instructions,
        "input": json.dumps(input_payload, ensure_ascii=False),
        "max_output_tokens": max(64, min(2_000, int(max_output_tokens))),
        "store": False,
    }
    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        settings.endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ONE-CRM/OpenAI-Integration",
            "Connection": "close",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise OpenAIConnectionError("A resposta da OpenAI excedeu o limite aceito pelo ONE CRM.")
            payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            raw_error = exc.read(512 * 1024)
            parsed_error = json.loads(raw_error.decode("utf-8")) if raw_error else {}
        except Exception:
            parsed_error = {}
        message = _error_message(parsed_error, f"A OpenAI retornou HTTP {exc.code}.")
        if exc.code in {401, 403}:
            raise OpenAIAuthenticationError("A chave da OpenAI foi rejeitada. Revise OPENAI_API_KEY.") from exc
        if exc.code == 429:
            raise OpenAIRateLimitError("A OpenAI recusou a chamada por limite de uso, saldo ou excesso de requisições.") from exc
        raise OpenAIConnectionError(f"Falha na OpenAI: {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OpenAIConnectionError("Não foi possível conectar à OpenAI dentro do tempo esperado.") from exc
    except json.JSONDecodeError as exc:
        raise OpenAIConnectionError("A OpenAI retornou uma resposta inválida.") from exc

    answer = _extract_output_text(payload)
    if not answer:
        raise OpenAIConnectionError("A OpenAI não retornou texto utilizável.")

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "answer": answer,
        "response_id": str(payload.get("id") or ""),
        "model": str(payload.get("model") or settings.model),
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


def test_openai_connection(model_override: str | None = None) -> dict[str, Any]:
    return create_openai_response(
        question="Responda apenas com: CONEXAO OK",
        context={"finalidade": "Teste técnico da integração do ONE CRM"},
        model_override=model_override,
        max_output_tokens=32,
    )
