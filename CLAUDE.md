# pub-project-auditor

<!-- audit-history-ref -->
## 순회 점검 이력
이 프로젝트의 누적 점검 이력은 `~/programs/docs/mac-main/pub-project-auditor/audit-history.md` 에 있다.
작업 시작 전 최근 지적사항을 먼저 확인하라.
상세 리포트 본문은 `~/programs/devs/test33-project-auditor/reports/pub-project-auditor/` 참조.
<!-- /audit-history-ref -->

<!-- project-review-ref -->
## 평가 보고서 (common-hub 평가 워크플로우, 2026-05-14 갱신)
작업 시작 전 다음 4개 파일을 순서대로 확인:
1. `~/programs/docs/mac-main/<project>/HANDOFF.md` 의 `## Common Hub Review Status` 자동 블록 (점수/verdict/mode 한눈에)
2. `~/programs/docs/mac-main/<project>/PROJECT-REVIEW.md` (최신 보고서, 단일 진실 원천)
3. `~/programs/docs/mac-main/<project>/PROJECT-REVIEW-RESPONSE.md` (이전 대응 내역 + 자동 추가된 `## Response For Review <ts>` 섹션들)
4. (선택) `~/programs/docs/mac-main/<project>/reviews/` 직전 2개로 추세 비교

**절대 규칙**
- `## Common Hub Review Status` 자동 블록은 **수동 수정 금지** (Common Hub 가 매 평가에서 덮어씀).
- 평가 대응 (Must Fix 처리 / 검증 증거 / Notes) 은 **반드시 `PROJECT-REVIEW-RESPONSE.md` 에** 작성. HANDOFF 본문 자체에 응답 박지 말 것.

평가 모드 3가지 — `local-use` / `handoff` (기본) / `public-release`.
Verdict 4단계 — `public-ready` / `ready-with-notes` / `needs-fixes` / `blocked`.
Gate Rules (README / secret / HANDOFF / `local-use` + `runVerification` 시 test/build 실패) 위반 시 점수 무시하고 즉시 처리.

재평가 호출 (camelCase 키 주의):
```bash
curl -sX POST -m 300 -H "Content-Type: application/json" \
  -d '{"project":"<name>","reviewMode":"local-use","runVerification":true}' \
  http://127.0.0.1:5038/api/project/review
```

중앙 누적 이력: `~/programs/docs/mac-main/common-hub/project-review-history.json`.
<!-- /project-review-ref -->

