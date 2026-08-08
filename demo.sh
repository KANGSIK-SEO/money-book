#!/usr/bin/env bash
# 전체 기능을 한 번에 훑어보는 데모 스크립트.
#   bash demo.sh
# ./demo-data 폴더를 새로 만들어 사용하므로 실제 데이터는 건드리지 않는다.
set -e

DATA="./demo-data"
APP="python3 -m budget_app --data-dir $DATA"

rm -rf "$DATA"
echo "### 1. 초기화 + 데이터 파일 자동 생성"
$APP info

echo
echo "### 2. CSV 가져오기 (샘플 11건)"
$APP import --file examples/sample.csv

echo
echo "### 3. 거래 추가 (비대화형 — 옵션을 모두 주면 질문을 건너뜀)"
$APP add --type expense --date 2026-08-09 --amount 12000 --category 식비 --memo "점심 김치찌개" --tags 점심,회사

echo
echo "### 4. 목록 (최신순 5건)"
$APP list --limit 5

echo
echo "### 5. 검색 (8월 식비)"
$APP search --from 2026-08-01 --to 2026-08-31 --category 식비

echo
echo "### 6. 예산 설정 후 월별 요약"
$APP budget set --month 2026-08 --amount 1500000
$APP budget set --month 2026-08 --amount 200000 --category 식비
$APP summary --month 2026-08 --top 5

echo
echo "### 7. 수정 / 삭제"
$APP update tx-00004 --amount 5500 --memo "라떼로 변경"
$APP delete tx-00011 --yes

echo
echo "### 8. 카테고리 관리 (사용 중 카테고리는 대체 없이는 삭제 불가)"
$APP category add --name 카페 --scope expense --description "커피 전용"
$APP category delete --name 문화 --replace-with 기타
$APP category list

echo
echo "### 9. 반복 거래 (보너스)"
$APP recurring add --type expense --day 25 --amount 55000 --category 통신 --memo "휴대폰 자동이체"
$APP recurring apply --month 2026-09

echo
echo "### 10. 내보내기 + 백업 (보너스)"
$APP export --file "$DATA/export-2026-08.csv" --month 2026-08
$APP backup --dest "$DATA/backup"

echo
echo "### 11. 오류 처리 (스택트레이스 대신 원인 + 힌트)"
$APP add --type expense --amount 1000 --category 없는카테고리 || true
$APP summary --month 2026-8 || true

echo
echo "데모 완료. 데이터: $DATA"
