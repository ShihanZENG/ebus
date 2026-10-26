"""模型网关端到端校验：真实调用一次模型，确认 lim_model_calls 落行且 token 非 NULL。

用法：python verify_model_gateway.py
"""
from sqlalchemy import desc, func, select

from app import lim_model_gateway as gw
from app.lim_models import LimModelCall


def _count(db):
    return db.scalar(select(func.count()).select_from(LimModelCall)) or 0


def main():
    with gw._sessions()() as db:
        before = _count(db)

    print('调用前 lim_model_calls 行数:', before)
    try:
        answer = gw.complete([{'role': 'user', 'content': '只回复两个字：收到'}], [], 30)
    except RuntimeError as exc:
        print('complete 失败（错误码保持兼容）:', exc)
        with gw._sessions()() as db:
            after = _count(db)
        print('调用后行数:', after, '（失败也应落一条 FAILED 观测记录）')
        return 1 if after == before else 0

    print('返回 content:', repr(str(answer.get('content'))[:60]))

    with gw._sessions()() as db:
        after = _count(db)
        row = db.scalars(select(LimModelCall).order_by(desc(LimModelCall.created_at)).limit(1)).first()

    print('调用后 lim_model_calls 行数:', after)
    if row is not None:
        print(f'  call_id={row.call_id}')
        print(f'  status={row.status}  provider={row.provider_id}  model={row.model}')
        print(f'  prompt_tokens={row.prompt_tokens}  completion_tokens={row.completion_tokens}  total={row.total_tokens}')
        print(f'  latency_ms={row.latency_ms}  cost={row.cost}  error_code={row.error_code}')

    ok = after > before and row is not None and row.status == 'SUCCEEDED' and row.total_tokens
    print('\n结论:', '通过 —— 网关已记录真实 token 用量' if ok else '未通过')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
