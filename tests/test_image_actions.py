import unittest
from copy import deepcopy
from image_actions import ImageActionController, BASE, FOLLOW


class ImageActionTests(unittest.TestCase):
    def setUp(self):
        self.state = {BASE: '01'}
        self.catalog = {'roles': [{'id': 'rest', 'label': '휴식'}],
                        'sets': [{'id': '01', 'label': '세트 01'}, {'id': 'pack:22', 'label': '가져온 세트 22'}],
                        'images': [{'ref': 'builtin:rest/rest_01.png', 'label': 'rest_01.png', 'role': 'rest', 'version': 'one'}]}
        self.controller = ImageActionController(lambda: deepcopy(self.catalog), lambda: deepcopy(self.state), self.write)

    def write(self, state):
        self.state = deepcopy(state)

    def proposal(self):
        return self.controller.propose({'kind': 'image', 'role': 'rest', 'ref': 'builtin:rest/rest_01.png'})

    def test_propose_cancel_and_duplicate_apply_never_silently_change_state(self):
        proposal = self.proposal()
        self.assertEqual(self.state, {BASE: '01'})
        self.controller.cancel(proposal['id'])
        self.assertEqual(self.controller.apply(proposal['id'])['status'], 'cancelled')
        self.assertEqual(self.state, {BASE: '01'})
        proposal = self.proposal()
        self.assertTrue(self.controller.apply(proposal['id'])['changed'])
        self.assertFalse(self.controller.apply(proposal['id'])['changed'])
        self.assertTrue(self.controller.undo()['changed'])
        self.assertEqual(self.state, {BASE: '01'})

    def test_changed_state_and_changed_asset_reject_stale_proposal(self):
        proposal = self.proposal()
        self.state[BASE] = 'pack:22'
        self.assertEqual(self.controller.apply(proposal['id'])['status'], 'stale')
        proposal = self.proposal()
        self.catalog['images'][0]['version'] = 'two'
        self.assertEqual(self.controller.apply(proposal['id'])['status'], 'stale')

    def test_unknown_image_and_ambiguous_scope_are_rejected(self):
        self.assertEqual(self.controller.propose({'kind': 'image', 'ref': 'file:///etc/passwd'})['status'], 'error')
        self.assertEqual(self.controller.propose({'kind': 'image', 'role': 'rest', 'ref': 'absolute:/tmp/a.png'})['status'], 'error')
        self.assertEqual(self.controller.propose({'kind': 'base_set', 'set_id': 'pack:99'})['status'], 'error')

    def test_follow_keeps_role_specific_scope_and_undo_respects_external_changes(self):
        self.state['rest'] = 'builtin:rest/rest_01.png'
        proposal = self.controller.propose({'kind': 'follow', 'role': 'rest'})
        self.controller.apply(proposal['id'])
        self.assertEqual(self.state['rest'], FOLLOW)
        self.assertEqual(self.state[BASE], '01')
        self.state[BASE] = 'pack:22'
        self.assertEqual(self.controller.undo()['status'], 'stale')

    def test_failed_persistence_does_not_consume_proposal_or_undo(self):
        def fail(_):
            raise OSError('disk full')
        self.controller.write_state = fail
        proposal = self.proposal()
        result = self.controller.apply(proposal['id'])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.state, {BASE: '01'})
        self.assertEqual(self.controller.undo()['status'], 'empty')
        self.controller.write_state = self.write
        self.assertEqual(self.controller.apply(proposal['id'])['status'], 'applied')

    def test_live_timer_role_context_does_not_expire_explicit_role_proposal(self):
        proposal = self.proposal()
        self.catalog['current_role'] = 'away'
        self.catalog['actual_current_ref'] = 'builtin:away/away_01.png'
        self.assertEqual(self.controller.apply(proposal['id'])['status'], 'applied')
