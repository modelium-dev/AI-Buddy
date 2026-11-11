"""Команды: python -m app.cli seed | seed-if-empty | reindex | check-llm | eval."""
from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.db import database


async def _init() -> None:
    if database.engine is None:
        database.init(get_settings().database_url)


async def seed(reset: bool = True) -> None:
    from app.llm import get_embedder
    from app.mcp_client import get_mcp
    from app.seed import seed_all

    await _init()
    if reset:
        await database.drop_all()
    await database.create_all()
    async with database.session() as session:
        await seed_all(session, get_mcp(), get_embedder(), get_settings().seed_dir)
    print("Сид загружен: пользователи, чек-лист, вики проиндексирована, задачи синхронизированы.")


async def seed_if_empty() -> None:
    from app.seed import is_seeded

    await _init()
    await database.create_all()
    async with database.session() as session:
        if await is_seeded(session):
            print("База уже заполнена — сид пропущен.")
            return
    await seed(reset=False)


async def reindex() -> None:
    from app.assistant.retrieval import index_documents, load_wiki
    from app.llm import get_embedder

    await _init()
    async with database.session() as session:
        count = await index_documents(session, load_wiki(get_settings().seed_dir), get_embedder())
        await session.commit()
    print(f"Проиндексировано чанков: {count}")


async def check_llm() -> int:
    from app.llm import get_embedder, get_llm

    s = get_settings()
    print(f"LLM_PROVIDER={s.llm_provider} LLM_MODEL={s.llm_model} EMBEDDINGS_MODEL={s.embeddings_model}")
    llm = get_llm()
    if llm.is_fake:
        print("Режим fake: внешний провайдер не используется. Для проверки ключа задайте LLM_PROVIDER=openai_compatible.")
        return 0
    try:
        reply = await llm.complete([{"role": "user", "content": "Ответь одним словом: ок"}])
        vectors = await get_embedder().embed(["проверка"])
    except Exception as exc:  # pragma: no cover - зависит от внешнего провайдера
        print(f"Ошибка подключения: {exc}")
        return 1
    print(f"Ответ модели: {reply!r}; размерность эмбеддинга: {len(vectors[0])}")  # pragma: no cover
    return 0  # pragma: no cover


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    args = argv if argv is not None else sys.argv[1:]
    command = args[0] if args else "help"
    if command == "seed":
        asyncio.run(seed())
    elif command == "seed-if-empty":
        asyncio.run(seed_if_empty())
    elif command == "reindex":
        asyncio.run(reindex())
    elif command == "check-llm":
        return asyncio.run(check_llm())
    elif command == "eval":
        from app.evaluation import run_cli

        return asyncio.run(run_cli(args[1] if len(args) > 1 else None))
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
