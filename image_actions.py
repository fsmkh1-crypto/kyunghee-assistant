"""Validated, explicit image proposals with optimistic concurrency and one-step undo."""
from __future__ import annotations

from copy import deepcopy
import uuid
from image_catalog import catalog_revision

FOLLOW = '__follow_selected_set__'
BASE = '__base_set__'


class ImageActionController:
    def __init__(self, catalog, read_state, write_state):
        self.catalog = catalog
        self.read_state = read_state
        self.write_state = write_state
        self.proposals = {}
        self.history = []

    def propose(self, action: dict) -> dict:
        try:
            catalog = self.catalog()
            action = {key: value for key, value in dict(action).items() if value is not None}
            roles = {item['id']: item['label'] for item in catalog['roles']}
            images = {item['ref']: item for item in catalog['images']}
            sets = {item['id']: item['label'] for item in catalog['sets']}
            kind = action.get('kind')
            preview = None
            if kind in {'image', 'follow'}:
                role = action.get('role')
                if role not in roles:
                    raise ValueError('바꿀 상황을 선택해 주세요. 전체 세트인지 특정 상황인지 확인이 필요합니다.')
                scope = roles[role] + ' 상황에만 적용'
                if kind == 'image':
                    ref = action.get('ref')
                    if ref not in images:
                        raise ValueError('목록에 있는 유효한 이미지를 선택해 주세요.')
                    action = {'kind': kind, 'role': role, 'ref': ref}
                    preview = ref
                    summary = f"{roles[role]} → {images[ref]['label']} · 다른 상황은 유지"
                else:
                    action = {'kind': kind, 'role': role}
                    summary = f'{roles[role]} → 전체 세트 따라가기'
            elif kind == 'base_set':
                set_id = str(action.get('set_id', ''))
                if set_id not in sets:
                    raise ValueError('목록에 있는 완전한 이미지 세트를 선택해 주세요.')
                action = {'kind': kind, 'set_id': set_id}
                scope = '전체 세트 · 상황별 수동 선택 유지'
                summary = f'전체 세트 → {sets[set_id]} · 상황별 수동 선택 유지'
                preview = next((item['ref'] for item in catalog['images'] if item.get('set_id') == set_id and item['role'] == 'default'), None)
            else:
                raise ValueError('지원하지 않는 이미지 변경입니다.')
            result = {'id': uuid.uuid4().hex, 'status': 'pending', 'changed': False,
                      'summary': summary, 'action': action, 'scope': scope, 'preview_ref': preview}
            self.proposals[result['id']] = {
                'result': result, 'before': deepcopy(self.read_state()),
                'catalog_revision': catalog_revision(catalog),
            }
            if len(self.proposals) > 128:
                self.proposals.pop(next(iter(self.proposals)))
            return deepcopy(result)
        except (ValueError, TypeError, KeyError) as exc:
            return {'status': 'error', 'changed': False, 'summary': str(exc)}

    def apply(self, proposal_id: str) -> dict:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return {'status': 'stale', 'changed': False, 'summary': '제안을 다시 만들어 주세요.'}
        result = proposal['result']
        if result['status'] != 'pending':
            return {**result, 'changed': False}
        if self.read_state() != proposal['before'] or catalog_revision(self.catalog()) != proposal['catalog_revision']:
            result.update(status='stale', changed=False, summary='이미지 설정이나 목록이 바뀌었습니다. 새 제안을 확인해 주세요.')
            return deepcopy(result)
        after = deepcopy(proposal['before'])
        action = result['action']
        if action['kind'] == 'base_set':
            after[BASE] = action['set_id']
        elif action['kind'] == 'follow':
            after[action['role']] = FOLLOW
        else:
            after[action['role']] = action['ref']
        try:
            self.write_state(after)
        except Exception as exc:
            return {**result, 'status': 'error', 'changed': False, 'summary': f'이미지 변경을 저장하지 못했습니다: {exc}'}
        self.history.append((deepcopy(proposal['before']), deepcopy(after)))
        self.history = self.history[-20:]
        result.update(status='applied', changed=after != proposal['before'])
        return deepcopy(result)

    def cancel(self, proposal_id: str) -> dict:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return {'status': 'stale', 'changed': False, 'summary': '제안이 만료되었습니다.'}
        result = proposal['result']
        if result['status'] == 'pending':
            result.update(status='cancelled', changed=False, summary='이미지 변경을 취소했습니다.')
        return {**result, 'changed': False}

    def undo(self) -> dict:
        if not self.history:
            return {'status': 'empty', 'changed': False, 'summary': '되돌릴 이미지 변경이 없습니다.'}
        before, after = self.history[-1]
        if self.read_state() != after:
            return {'status': 'stale', 'changed': False, 'summary': '설정이 이후 변경되어 되돌릴 수 없습니다.'}
        try:
            self.write_state(deepcopy(before))
        except Exception as exc:
            return {'status': 'error', 'changed': False, 'summary': f'되돌리기를 저장하지 못했습니다: {exc}'}
        self.history.pop()
        return {'status': 'undone', 'changed': True, 'summary': '직전 이미지 변경을 되돌렸습니다.'}
