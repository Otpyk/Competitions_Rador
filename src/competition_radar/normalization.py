"""Conservative identity normalization before B makes field decisions."""

from .schemas import CandidateContest, IDENTITY_FIELDS
from .validation import ContractError

_ENGLISH_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")

def normalize_text(value: str) -> str:
    return " ".join(value.split()).translate(_ENGLISH_LOWER)


def merge_candidates(candidates: list[CandidateContest]) -> list[CandidateContest]:
    """Merge only complete, unambiguous five-part identities; retain every claim."""
    result = []
    index_by_key = {}
    record_ids, member_ids, claim_ids = set(), set(), set()
    for candidate in candidates:
        if candidate.record_id in record_ids:
            raise ContractError(f"赛事记录 ID 重复：{candidate.record_id}")
        record_ids.add(candidate.record_id)
        for member_id in candidate.member_ids:
            if member_id in member_ids:
                raise ContractError(f"原始赛事记录被重复提供：{member_id}")
            member_ids.add(member_id)
        for claim in candidate.claims:
            if claim.claim_id in claim_ids:
                raise ContractError(f"候选 ID 在批次内重复：{claim.claim_id}")
            claim_ids.add(claim.claim_id)

        identity = []
        for field in IDENTITY_FIELDS:
            values = {normalize_text(c.value) for c in candidate.claims if c.field == field}
            if len(values) != 1:
                break
            identity.append(next(iter(values)))
        key = tuple(identity) if len(identity) == len(IDENTITY_FIELDS) else None
        if key is None or key not in index_by_key:
            result.append(candidate.model_copy(deep=True))
            if key is not None:
                index_by_key[key] = len(result) - 1
        else:
            target = result[index_by_key[key]]
            target.member_ids.extend(candidate.member_ids)
            target.claims.extend(claim.model_copy(deep=True) for claim in candidate.claims)
    return result
