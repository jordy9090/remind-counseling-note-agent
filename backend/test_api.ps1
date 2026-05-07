$body = @{
  case_id = "TEST-001"
  session_no = 3
  counselor_memo = "내담자가 최근 직장 내 대인관계 갈등으로 스트레스를 호소함. 수면 장애 동반."
  transcript = "상담사: 요즘 어떠세요? 내담자: 회사에서 팀장이랑 계속 부딪혀요. 밤에 잠도 잘 못 자고... 상담사: 구체적으로 어떤 상황이었나요? 내담자: 제 의견을 무시하는 느낌이에요."
  prev_summary = "2회기: 내담자는 직장 적응 스트레스를 호소하였으며 자기주장 훈련의 필요성이 논의되었음."
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/notes/session-draft" -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
