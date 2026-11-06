"""Shared synthetic regressions for local name discovery and privacy boundaries."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.services.deidentification import deidentify_text
from app.services.deidentification_preview import preview_items
from app.services.korean_person_names import discover_person_names, mask_person_names, name_pattern, person_replacements
from app.services.storage_deidentification import deidentify_json


class KoreanPersonNameTests(unittest.TestCase):
    def test_shared_browser_backend_fixtures(self):
        fixtures = json.loads((Path(__file__).parent / 'fixtures/korean_person_names.json').read_text(encoding='utf-8'))
        for case in fixtures:
            with self.subTest(text=case['text']):
                self.assertEqual(discover_person_names(case['text'], case.get('known_names', [])), case['names'])
                masked = case['text']
                for name in sorted(case['names'], key=len, reverse=True):
                    masked = name_pattern(name, exact_identity=case['names'][name] == name).sub('[인물]', masked)
                for phrase in case.get('preserve', []):
                    self.assertIn(phrase, masked)

    def test_audio_masking_preserves_identity_and_requires_no_provider(self):
        text = '친구 김하린에게 전화했어요. 하린이는 안 갔어요. 누나 김소윤이요. 소윤에게 2번 말했어요.'
        with patch('app.services.llm.get_structured_llm', side_effect=AssertionError('no raw text to provider')):
            masked, candidates = deidentify_text(text, source='corrected_audio_transcript')
        self.assertEqual(masked, '친구 [인물 B]에게 전화했어요. [인물 B]이는 안 갔어요. 누나 [인물 C]이요. [인물 C]에게 2번 말했어요.')
        self.assertEqual([c.category for c in candidates], ['person_name'])
        self.assertNotIn('김하린', json.dumps([c.model_dump() for c in candidates], ensure_ascii=False))
        self.assertEqual(deidentify_text(masked)[0], masked)

    def test_ambiguous_given_name_does_not_merge_two_people(self):
        replacements = person_replacements('친구 김하린과 동료 박하린. 하린이는 먼저 갔다.')
        self.assertNotEqual(replacements['김하린'], replacements['박하린'])
        self.assertEqual(replacements['하린'], '[인물 확인 필요]')
        items = {i.original: i.replacement for i in preview_items(
            ['김하린과 친구 박하린. 하린이는 먼저 갔다.'], client_name='김하린',
        ).items}
        self.assertEqual(items['김하린'], '내담자 A')
        self.assertEqual(items['하린'], '인물 확인 필요')

    def test_preview_and_storage_discover_aliases_across_fields(self):
        texts = ['친구 김하린에게 말했어요.', '하린이는 안 갔고 누나 김소윤이요. 소윤에게 2번 말했어요.']
        items = {i.original: i.replacement for i in preview_items(texts).items}
        self.assertEqual(items['김하린'], items['하린'])
        self.assertEqual(items['김소윤'], items['소윤'])
        masked, _ = deidentify_json({'draft_id': 'draft_김하린', 'a': texts[0], 'b': texts[1]})
        self.assertEqual(masked['draft_id'], 'draft_김하린')
        self.assertNotIn('김하린', masked['a'])
        self.assertNotIn('하린', masked['b'])
        self.assertIn('안 갔고', masked['b'])

    def test_long_transcript_tail_and_particle_boundaries(self):
        text = ('내담자: 지원을 받지 않았다. 2회기다.\n' * 4000) + '친구 김하린. 하린이는 누나 김소윤에게 말했어요.'
        masked, _ = mask_person_names(text)
        self.assertTrue(masked.startswith('내담자: 지원을 받지 않았다. 2회기다.'))
        for name in ['김하린', '하린', '김소윤']:
            self.assertNotIn(name, masked)

    def test_explicit_short_names_are_not_treated_as_inferred_aliases(self):
        text = '이름: 지원. 지원은 안 갔다. 이름: 사랑. 사랑도 말했다.'
        self.assertEqual(mask_person_names(text)[0], '이름: [인물 B]. [인물 B]은 안 갔다. 이름: [인물 C]. [인물 C]도 말했다.')
        masked, _ = deidentify_json({'client_alias': '지혜', 'memo': '지혜는 안 갔다.'}, known_names=['지혜'])
        self.assertEqual(masked, {'client_alias': '지O', 'memo': '지O는 안 갔다.'})


if __name__ == '__main__':
    unittest.main()
