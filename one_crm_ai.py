from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_GROQ_API_URL = "https://api.groq.com/openai/v1/responses"
DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_TIMEOUT_SECONDS = 35.0
SUPPORTED_PROVIDERS = {"auto", "groq", "openai", "local"}


class AIIntegrationError(RuntimeError):
    """Erro base da camada de inteligência externa do ONE CRM."""


class AIConfigurationError(AIIntegrationError):
    """O provedor solicitado não foi configurado corretamente."""


class AIAuthenticationError(AIIntegrationError):
    """A credencial do provedor foi rejeitada."""


class AIRateLimitError(AIIntegrationError):
    """O provedor recusou a chamada por limite de uso ou saldo."""


class AIConnectionError(AIIntegrationError):
    """Não foi possível concluir a comunicação com o provedor."""


# Compatibilidade com versões 1.8 e testes antigos.
OpenAIIntegrationError = AIIntegrationError
OpenAIConfigurationError = AIConfigurationError
OpenAIAuthenticationError = AIAuthenticationError
OpenAIRateLimitError = AIRateLimitError
OpenAIConnectionError = AIConnectionError


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    label: str
    configured: bool
    api_key: str
    model: str
    model_source: str
    endpoint: str


@dataclass(frozen=True)
class AISettings:
    enabled: bool
    requested_provider: str
    active_provider: str
    local_fallback: bool
    timeout_seconds: float
    groq: ProviderSettings
    openai: ProviderSettings


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _normalize_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    return provider if provider in SUPPORTED_PROVIDERS else "auto"


def _safe_timeout() -> float:
    try:
        value = float(os.getenv("ONE_CRM_AI_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        value = DEFAULT_TIMEOUT_SECONDS
    return min(120.0, max(5.0, value))


def _provider_model(
    env_name: str,
    override: str | None,
    default: str,
) -> tuple[str, str]:
    environment_model = (os.getenv(env_name) or "").strip()
    database_model = (override or "").strip()
    model = environment_model or database_model or default
    source = "environment" if environment_model else "database" if database_model else "default"
    return model, source


def get_ai_settings(
    *,
    provider_override: str | None = None,
    groq_model_override: str | None = None,
    openai_model_override: str | None = None,
) -> AISettings:
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    groq_model, groq_model_source = _provider_model(
        "GROQ_MODEL", groq_model_override, DEFAULT_GROQ_MODEL
    )
    openai_model, openai_model_source = _provider_model(
        "OPENAI_MODEL", openai_model_override, DEFAULT_OPENAI_MODEL
    )

    environment_provider = (os.getenv("ONE_CRM_AI_PROVIDER") or os.getenv("AI_PROVIDER") or "").strip()
    requested_provider = _normalize_provider(environment_provider or provider_override or "auto")
    local_fallback = _env_flag("ONE_CRM_AI_LOCAL_FALLBACK", True)
    enabled_default = bool(groq_key or openai_key or local_fallback)
    enabled = _env_flag("ONE_CRM_AI_ENABLED", enabled_default)

    if requested_provider == "groq":
        active_provider = "groq" if groq_key else "local" if local_fallback else "groq"
    elif requested_provider == "openai":
        active_provider = "openai" if openai_key else "local" if local_fallback else "openai"
    elif requested_provider == "local":
        active_provider = "local"
    else:
        active_provider = "groq" if groq_key else "openai" if openai_key else "local"

    return AISettings(
        enabled=enabled,
        requested_provider=requested_provider,
        active_provider=active_provider,
        local_fallback=local_fallback,
        timeout_seconds=_safe_timeout(),
        groq=ProviderSettings(
            provider="groq",
            label="GroqCloud",
            configured=bool(groq_key),
            api_key=groq_key,
            model=groq_model,
            model_source=groq_model_source,
            endpoint=(os.getenv("GROQ_API_URL") or DEFAULT_GROQ_API_URL).strip(),
        ),
        openai=ProviderSettings(
            provider="openai",
            label="OpenAI",
            configured=bool(openai_key),
            api_key=openai_key,
            model=openai_model,
            model_source=openai_model_source,
            endpoint=(os.getenv("OPENAI_API_URL") or DEFAULT_OPENAI_API_URL).strip(),
        ),
    )


def _provider_public(settings: ProviderSettings) -> dict[str, Any]:
    return {
        "provider": settings.provider,
        "label": settings.label,
        "configured": settings.configured,
        "model": settings.model,
        "model_source": settings.model_source,
        "key_source": "environment" if settings.configured else "missing",
        "endpoint": settings.endpoint,
    }


def public_ai_status(
    *,
    provider_override: str | None = None,
    groq_model_override: str | None = None,
    openai_model_override: str | None = None,
) -> dict[str, Any]:
    settings = get_ai_settings(
        provider_override=provider_override,
        groq_model_override=groq_model_override,
        openai_model_override=openai_model_override,
    )
    active = (
        settings.groq
        if settings.active_provider == "groq"
        else settings.openai
        if settings.active_provider == "openai"
        else None
    )
    return {
        "enabled": settings.enabled,
        "ready": settings.enabled and (
            settings.active_provider == "local" or bool(active and active.configured)
        ),
        "requested_provider": settings.requested_provider,
        "active_provider": settings.active_provider,
        "provider_label": active.label if active else "Análise local",
        "model": active.model if active else "motor-local",
        "model_source": active.model_source if active else "built-in",
        "local_fallback": settings.local_fallback,
        "external_configured": settings.groq.configured or settings.openai.configured,
        "providers": {
            "groq": _provider_public(settings.groq),
            "openai": _provider_public(settings.openai),
            "local": {
                "provider": "local",
                "label": "Análise local",
                "configured": True,
                "model": "motor-local",
                "model_source": "built-in",
                "key_source": "none",
            },
        },
    }


def public_openai_status(model_override: str | None = None) -> dict[str, Any]:
    """Compatibilidade: devolve somente o estado do provedor OpenAI."""
    status = public_ai_status(openai_model_override=model_override)
    provider = dict(status["providers"]["openai"])
    provider.update(
        {
            "enabled": status["enabled"],
            "ready": status["enabled"] and provider["configured"],
        }
    )
    return provider


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
    if texts:
        return "\n\n".join(texts).strip()
    # Alguns endpoints compatíveis devolvem o texto em output_text direto.
    direct = payload.get("output_text")
    return direct.strip() if isinstance(direct, str) else ""


def _error_details(payload: Any, fallback: str) -> tuple[str, str]:
    code = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            raw_code = error.get("code") or error.get("type")
            code = str(raw_code or "").strip()
            if isinstance(message, str) and message.strip():
                return message.strip(), code
        if isinstance(error, str) and error.strip():
            return error.strip(), code
    return fallback, code


def _request_provider(
    *,
    provider: ProviderSettings,
    question: str,
    context: dict[str, Any],
    timeout_seconds: float,
    max_output_tokens: int,
) -> dict[str, Any]:
    if not provider.configured:
        variable = "GROQ_API_KEY" if provider.provider == "groq" else "OPENAI_API_KEY"
        raise AIConfigurationError(f"{variable} não foi configurada no Railway.")

    instructions = (
        "Você é o ONE Intelligence, assistente operacional do ONE CRM. "
        "Responda sempre em português do Brasil, de forma objetiva, profissional e útil. "
        "Use exclusivamente os dados fornecidos no contexto. Não invente clientes, datas, status, valores ou fatos. "
        "Diferencie claramente fatos registrados de recomendações. "
        "Não revele nem solicite CPF, telefone, e-mail, endereço completo, senha, chave de API ou qualquer segredo. "
        "Não afirme que executou alterações no CRM. Você apenas analisa e sugere ações. "
        "Quando o contexto for insuficiente, diga exatamente qual dado está faltando."
    )
    request_payload: dict[str, Any] = {
        "model": provider.model,
        "instructions": instructions,
        "input": json.dumps(
            {"contexto_one_crm": context, "pergunta": question},
            ensure_ascii=False,
        ),
        "max_output_tokens": max(64, min(2_000, int(max_output_tokens))),
    }
    # A Responses API da Groq não aceita o parâmetro store.
    if provider.provider == "openai":
        request_payload["store"] = False

    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        provider.endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"ONE-CRM/{provider.label}",
            "Connection": "close",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise AIConnectionError(
                    f"A resposta do provedor {provider.label} excedeu o limite aceito pelo ONE CRM."
                )
            payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            raw_error = exc.read(512 * 1024)
            parsed_error = json.loads(raw_error.decode("utf-8")) if raw_error else {}
        except Exception:
            parsed_error = {}
        message, error_code = _error_details(
            parsed_error, f"{provider.label} retornou HTTP {exc.code}."
        )
        if exc.code in {401, 403}:
            variable = "GROQ_API_KEY" if provider.provider == "groq" else "OPENAI_API_KEY"
            raise AIAuthenticationError(
                f"A chave do {provider.label} foi rejeitada. Revise {variable}."
            ) from exc
        if exc.code == 429:
            if error_code in {"insufficient_quota", "billing_hard_limit_reached"}:
                raise AIRateLimitError(
                    f"{provider.label} recusou a chamada por falta de saldo ou limite financeiro."
                ) from exc
            raise AIRateLimitError(
                f"{provider.label} atingiu o limite temporário de uso. Tente novamente mais tarde."
            ) from exc
        if exc.code == 404 and "model" in message.lower():
            raise AIConfigurationError(
                f"O modelo {provider.model} não está disponível no {provider.label}."
            ) from exc
        raise AIConnectionError(f"Falha no {provider.label}: {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIConnectionError(
            f"Não foi possível conectar ao {provider.label} dentro do tempo esperado."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AIConnectionError(f"{provider.label} retornou uma resposta inválida.") from exc

    answer = _extract_output_text(payload)
    if not answer:
        raise AIConnectionError(f"{provider.label} não retornou texto utilizável.")

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "answer": answer,
        "response_id": str(payload.get("id") or ""),
        "model": str(payload.get("model") or provider.model),
        "provider": provider.provider,
        "provider_label": provider.label,
        "fallback_used": False,
        "fallback_reason": "",
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


def _percentage(part: int, total: int) -> float:
    return round((part * 100 / total), 1) if total else 0.0


def create_local_response(
    *,
    question: str,
    context: dict[str, Any],
    fallback_reason: str = "",
) -> dict[str, Any]:
    metrics = context.get("indicadores") if isinstance(context.get("indicadores"), dict) else {}
    total = int(metrics.get("total_vendas") or 0)
    installed = int(metrics.get("instaladas") or 0)
    canceled = int(metrics.get("canceladas") or 0)
    pending_bio = int(metrics.get("biometrias_pendentes") or 0)
    late = int(metrics.get("agendamentos_atrasados") or 0)
    today = int(metrics.get("vendas_hoje") or 0)
    lines = ["**Análise local do ONE CRM**"]
    if fallback_reason:
        lines.append(
            "O provedor externo não respondeu, então o sistema utilizou os indicadores locais sem consumir API."
        )

    sale = context.get("venda_especifica")
    if isinstance(sale, dict):
        lines.append(
            f"Venda #{sale.get('id')}: status {sale.get('status') or 'não informado'}, "
            f"ativação {sale.get('ativacao') or 'não informada'}, biometria {sale.get('biometria') or 'não informada'} "
            f"e instalação {sale.get('instalacao') or 'não informada'}."
        )
        recommendations: list[str] = []
        bio = str(sale.get("biometria") or "").lower()
        installation = str(sale.get("instalacao") or "").lower()
        if "pendente" in bio or "retorno" in bio or "prometeu" in bio:
            recommendations.append("priorizar o contato de biometria")
        if "aguard" in installation or "agend" in installation:
            recommendations.append("confirmar data e período da instalação")
        if sale.get("agendamento_data"):
            recommendations.append(f"validar o agendamento de {sale.get('agendamento_data')}")
        if recommendations:
            lines.append("Próxima ação sugerida: " + "; ".join(recommendations) + ".")
        else:
            lines.append("Não há uma pendência operacional evidente nos campos disponíveis.")
    else:
        lines.append(
            f"Há {total} venda(s) no escopo, {today} criada(s) hoje, {installed} instalada(s) "
            f"e {canceled} cancelada(s). Conversão acumulada: {_percentage(installed, total)}%."
        )
        priorities: list[str] = []
        if late:
            priorities.append(f"tratar {late} agendamento(s) atrasado(s)")
        if pending_bio:
            priorities.append(f"acompanhar {pending_bio} biometria(s) pendente(s)")
        if canceled and total:
            priorities.append(f"revisar cancelamentos ({_percentage(canceled, total)}% do total)")
        lines.append(
            "Prioridades: " + ("; ".join(priorities) if priorities else "nenhum alerta crítico pelos indicadores atuais") + "."
        )

        uf_rows = context.get("vendas_por_uf")
        if isinstance(uf_rows, list) and uf_rows:
            best = sorted(
                (row for row in uf_rows if isinstance(row, dict)),
                key=lambda row: (int(row.get("total") or 0), int(row.get("instaladas") or 0)),
                reverse=True,
            )[:5]
            if best:
                lines.append(
                    "Estados com maior volume no escopo: "
                    + ", ".join(
                        f"{row.get('uf')}: {int(row.get('total') or 0)} venda(s)"
                        for row in best
                    )
                    + "."
                )

    lowered = question.lower()
    if any(term in lowered for term in {"estado", "uf", "região", "regiao"}) and not context.get("vendas_por_uf"):
        lines.append("O contexto atual não possui distribuição por UF suficiente para indicar estados com segurança.")
    if any(term in lowered for term in {"equipe", "ranking", "vendedor"}) and context.get("equipes"):
        teams = [row for row in context.get("equipes") or [] if isinstance(row, dict)]
        teams.sort(key=lambda row: int(row.get("total") or 0), reverse=True)
        if teams:
            lines.append(
                "Equipes com maior volume: "
                + ", ".join(f"{row.get('equipe')}: {row.get('total')}" for row in teams[:5])
                + "."
            )

    return {
        "answer": "\n\n".join(lines),
        "response_id": "local",
        "model": "motor-local",
        "provider": "local",
        "provider_label": "Análise local",
        "fallback_used": bool(fallback_reason),
        "fallback_reason": fallback_reason,
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }


def _candidate_providers(settings: AISettings) -> list[ProviderSettings]:
    if settings.requested_provider == "groq":
        return [settings.groq]
    if settings.requested_provider == "openai":
        return [settings.openai]
    if settings.requested_provider == "local":
        return []
    candidates: list[ProviderSettings] = []
    if settings.groq.configured:
        candidates.append(settings.groq)
    if settings.openai.configured:
        candidates.append(settings.openai)
    return candidates


def create_ai_response(
    *,
    question: str,
    context: dict[str, Any],
    provider_override: str | None = None,
    groq_model_override: str | None = None,
    openai_model_override: str | None = None,
    max_output_tokens: int = 900,
) -> dict[str, Any]:
    clean_question = (question or "").strip()
    if not clean_question:
        raise ValueError("A pergunta não pode estar vazia.")
    if len(clean_question) > 2_000:
        raise ValueError("A pergunta excede o limite de 2.000 caracteres.")

    settings = get_ai_settings(
        provider_override=provider_override,
        groq_model_override=groq_model_override,
        openai_model_override=openai_model_override,
    )
    if not settings.enabled:
        raise AIConfigurationError("A inteligência artificial está desativada no ambiente.")
    if settings.requested_provider == "local":
        return create_local_response(question=clean_question, context=context)

    candidates = _candidate_providers(settings)
    if not candidates and settings.local_fallback:
        return create_local_response(question=clean_question, context=context)

    errors: list[str] = []
    for provider in candidates:
        try:
            return _request_provider(
                provider=provider,
                question=clean_question,
                context=context,
                timeout_seconds=settings.timeout_seconds,
                max_output_tokens=max_output_tokens,
            )
        except (AIConfigurationError, AIAuthenticationError, AIRateLimitError, AIConnectionError) as exc:
            errors.append(str(exc))
            if settings.requested_provider != "auto":
                break

    if settings.local_fallback:
        reason = errors[-1] if errors else "Nenhum provedor externo foi configurado."
        return create_local_response(
            question=clean_question,
            context=context,
            fallback_reason=reason,
        )

    if errors:
        raise AIConnectionError(errors[-1])
    raise AIConfigurationError(
        "Nenhum provedor externo foi configurado. Defina GROQ_API_KEY ou OPENAI_API_KEY."
    )


def create_openai_response(
    *,
    question: str,
    context: dict[str, Any],
    model_override: str | None = None,
    max_output_tokens: int = 900,
) -> dict[str, Any]:
    """Compatibilidade com a API interna da versão 1.8."""
    return create_ai_response(
        question=question,
        context=context,
        provider_override="openai",
        openai_model_override=model_override,
        max_output_tokens=max_output_tokens,
    )


def test_ai_connection(
    *,
    provider: str,
    groq_model_override: str | None = None,
    openai_model_override: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_provider(provider)
    if normalized not in {"groq", "openai", "local"}:
        raise AIConfigurationError("Escolha Groq, OpenAI ou Local para o teste.")
    if normalized == "local":
        return create_local_response(
            question="Teste técnico",
            context={"indicadores": {}},
        )
    settings = get_ai_settings(
        provider_override=normalized,
        groq_model_override=groq_model_override,
        openai_model_override=openai_model_override,
    )
    selected = settings.groq if normalized == "groq" else settings.openai
    return _request_provider(
        provider=selected,
        question="Responda apenas com: CONEXAO OK",
        context={"finalidade": "Teste técnico da integração do ONE CRM"},
        timeout_seconds=settings.timeout_seconds,
        max_output_tokens=32,
    )


def test_openai_connection(model_override: str | None = None) -> dict[str, Any]:
    return test_ai_connection(provider="openai", openai_model_override=model_override)
