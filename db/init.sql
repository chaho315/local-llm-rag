-- =====================================================================
--  RAG 테스트용 DB 초기화 (스키마 OLLAMA_LLM / 계정 llmuser / 표 MMS_TEST_TB)
--  ※ 전부 합성(가짜) 데이터입니다. 개인정보/결제정보 없음.
--  실행: mysql -h 127.0.0.1 -u root --default-character-set=utf8mb4 < init.sql
-- =====================================================================

CREATE DATABASE IF NOT EXISTS OLLAMA_LLM DEFAULT CHARACTER SET utf8mb4;

-- 계정: 읽기전용(SELECT)만 부여 → RAG 설계(읽기전용)와 일치
CREATE USER IF NOT EXISTS 'llmuser'@'%'         IDENTIFIED BY 'CHANGE_ME_PASSWORD';
CREATE USER IF NOT EXISTS 'llmuser'@'localhost' IDENTIFIED BY 'CHANGE_ME_PASSWORD';
GRANT SELECT ON OLLAMA_LLM.* TO 'llmuser'@'%';
GRANT SELECT ON OLLAMA_LLM.* TO 'llmuser'@'localhost';
FLUSH PRIVILEGES;

USE OLLAMA_LLM;

DROP TABLE IF EXISTS MMS_TEST_TB;
CREATE TABLE MMS_TEST_TB (
  MSG_ID          INT AUTO_INCREMENT PRIMARY KEY,   -- 1. 메시지 ID
  MSG_TITLE       VARCHAR(200),                      -- 2. 제목
  MSG_CONTENT     TEXT,                              -- 3. 본문
  MSG_TYPE        VARCHAR(20),                       -- 4. 유형(NOTICE/PROMO/INFO/ALERT)
  SENDER_DEPT     VARCHAR(50),                       -- 5. 발신 부서
  RECIPIENT_GROUP VARCHAR(50),                       -- 6. 수신 그룹(개인 아님)
  STATUS          VARCHAR(20),                       -- 7. 상태(SENT/DRAFT/FAILED)
  PRIORITY        INT,                               -- 8. 우선순위
  SEND_DATE       DATE,                              -- 9. 발송일
  USE_YN          CHAR(1)                            -- 10. 사용여부
) DEFAULT CHARSET=utf8mb4;

INSERT INTO MMS_TEST_TB
 (MSG_TITLE, MSG_CONTENT, MSG_TYPE, SENDER_DEPT, RECIPIENT_GROUP, STATUS, PRIORITY, SEND_DATE, USE_YN)
VALUES
('시스템 정기점검 안내','오는 주말 토요일 00시부터 04시까지 결제 시스템 정기점검이 진행됩니다. 해당 시간 동안 결제 및 정산 서비스 이용이 일시 중단되니 업무에 참고 바랍니다.','NOTICE','인프라운영팀','전체','SENT',1,'2026-07-04','Y'),
('신규 간편결제 프로모션','7월 한 달간 신규 간편결제를 등록하는 가맹점 고객에게 결제액의 5% 캐시백을 제공합니다. 자세한 내용은 사내 이벤트 페이지를 확인하세요.','PROMO','마케팅팀','가맹점','SENT',2,'2026-07-01','Y'),
('정산 주기 변경 안내','8월부터 가맹점 정산 주기가 월 2회에서 주 1회로 변경됩니다. 매주 수요일에 정산이 이루어지며, 첫 적용일은 8월 6일입니다.','NOTICE','정산팀','가맹점','SENT',1,'2026-07-10','Y'),
('MMS 발송 실패 재처리 가이드','MMS 발송이 실패한 경우 관리자 콘솔의 재처리 메뉴에서 최대 3회까지 자동 재시도가 가능합니다. 3회 초과 실패 건은 수동 확인이 필요합니다.','INFO','메시징개발팀','개발자','SENT',3,'2026-06-28','Y'),
('보안 정책 업데이트','정보보안 강화를 위해 모든 임직원 계정의 비밀번호는 90일마다 변경해야 합니다. 미변경 시 계정이 일시 잠금되니 기한 내 변경 바랍니다.','ALERT','정보보안팀','임직원','SENT',1,'2026-07-05','Y'),
('신규 결제 API v2 출시','신규 결제 연동 API v2가 출시되었습니다. 기존 v1은 12월까지 지원되며 이후 종료 예정이니 파트너사는 마이그레이션을 준비해 주세요.','INFO','플랫폼개발팀','파트너사','DRAFT',2,'2026-07-12','Y'),
('고객센터 운영시간 변경','7월부터 고객센터 운영시간이 평일 09시~18시로 조정됩니다. 주말 및 공휴일 상담은 챗봇으로만 제공됩니다.','NOTICE','CS팀','전체','SENT',2,'2026-07-02','Y'),
('사내 교육: 개인정보보호','전 임직원 대상 개인정보보호 의무교육이 7월 20일부터 온라인으로 진행됩니다. 이수 기한은 7월 31일까지입니다.','NOTICE','인사팀','임직원','SENT',2,'2026-07-08','Y');
