"""Known-answer tests: prevent lexical quality from hiding speaker failures."""
from __future__ import annotations
import unittest
from benchmarks.stt_evaluate import boundary_score, diarization_error, evaluate, itn_characters


class EvaluationTests(unittest.TestCase):
    def test_label_permutation_is_not_a_speaker_error_but_collapsed_speakers_are(self):
        ref = [{"segment_id": "1", "start": 0, "end": 1, "text": "안 갔다", "speaker": "client"},
               {"segment_id": "2", "start": 1, "end": 2, "text": "네", "speaker": "counselor"}]
        hyp = [{**s, "speaker": f"speaker_{i}"} for i, s in enumerate(ref)]
        data = {"segments": ref, "duration_seconds": 2}
        perfect = evaluate(data, {"segments": hyp, "diarization_segments": hyp})
        self.assertEqual(0, perfect["korean_cer"])
        self.assertEqual(0, perfect["speaker_attribution_error_on_matched_characters"])
        self.assertEqual(0, perfect["diarization"]["der"])
        collapsed = [{**s, "speaker": "one"} for s in hyp]
        broken = evaluate(data, {"segments": collapsed, "diarization_segments": collapsed})
        self.assertEqual(0, broken["korean_cer"])
        self.assertGreater(broken["speaker_attribution_error_on_matched_characters"], 0)
        self.assertEqual(0.5, broken["diarization"]["der"])

    def test_overlap_miss_is_scored_and_extra_segmentation_is_penalized(self):
        ref = [{"start": 0, "end": 2, "speaker": "a"}, {"start": 1, "end": 2, "speaker": "b"}]
        score = diarization_error(ref, [{"start": 0, "end": 2, "speaker": "x"}], 2)
        self.assertAlmostEqual(1 / 3, score["miss"])
        ref = [{"start": 0, "speaker": "a"}, {"start": 3, "speaker": "b"}]
        hyp = [ref[0], {"start": 1.5, "speaker": "a"}, ref[1]]
        self.assertEqual(1, boundary_score(ref, hyp)["extra_boundaries"])

    def test_itn_equivalence_does_not_erase_negation_or_wrong_numbers(self):
        self.assertEqual(itn_characters("일곱 시 삼십 분"), itn_characters("7시 30분"))
        self.assertNotEqual(itn_characters("안 갔다"), itn_characters("갔다"))
        self.assertNotEqual(itn_characters("세 번"), itn_characters("2번"))

    def test_partial_sentence_omission_is_visible_despite_time_overlap(self):
        segment = {"segment_id": "ref", "start": 0, "end": 5, "speaker": "client", "text": "안 갔다. 약은 먹지 않았어요."}
        result = evaluate({"segments": [segment], "duration_seconds": 5},
                          {"segments": [{**segment, "text": "안 갔다."}]})
        self.assertEqual([], result["uncovered_reference_turns"])
        self.assertTrue(result["lexical_omission_candidates"])
        self.assertIn("먹지않았어요", result["lexical_omission_candidates"][0]["text"])

    def test_display_edit_proxy_exposes_spacing_and_punctuation_hidden_by_cer(self):
        segment = {"segment_id": "ref", "start": 0, "end": 2, "speaker": "client", "text": "안 갔다."}
        result = evaluate({"segments": [segment], "duration_seconds": 2},
                          {"segments": [{**segment, "text": "안갔 다"}]})
        self.assertEqual(0, result["korean_cer"])
        self.assertGreater(result["product_proxy"]["display_text_edits_including_spacing_punctuation"], 0)
        self.assertIsNone(result["product_proxy"]["human_correction_minutes"])

    def test_added_outro_is_visible_even_inside_a_real_speech_turn(self):
        segment = {"segment_id": "ref", "start": 0, "end": 3, "speaker": "client", "text": "안 갔다."}
        result = evaluate({"segments": [segment], "duration_seconds": 3},
                          {"segments": [{**segment, "text": "안 갔다. 영상편집 및 광고를 포함합니다."}]})
        self.assertEqual([], result['silence_output_candidates'])
        self.assertEqual([], result['repetition_candidates'])
        self.assertIn('영상편집', result['lexical_insertion_candidates'][0]['text'])


if __name__ == "__main__":
    unittest.main()
