"""Compatibilidade com o nome de teste usado na versão 1.8.

A validação atual cobre GroqCloud, OpenAI e fallback local.
"""
from ai_providers_test import main

if __name__ == "__main__":
    raise SystemExit(main())
