# 초기화 및 데이터베이스 생성
DROP DATABASE IF EXISTS netclass_db;
CREATE DATABASE netclass_db;
USE netclass_db;

# 설치 위치 정보 테이블
CREATE TABLE Location (
    location_id INT AUTO_INCREMENT PRIMARY KEY,
    location_name VARCHAR(50) NOT NULL,
    floor VARCHAR(20) NOT NULL # (B1, B2, IFZONE 저장 가능)
);

# 관리자 계정 테이블
CREATE TABLE Admin (
    admin_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(50) NOT NULL
);

# PC 자산 정보 테이블
CREATE TABLE PC (
    pc_id INT AUTO_INCREMENT PRIMARY KEY,
    pc_name VARCHAR(50) UNIQUE,
    location_id INT,
    ip_address VARCHAR(15) NOT NULL,
    current_mode ENUM('Recovery', 'Maintenance') DEFAULT 'Recovery',
    status ENUM('Online', 'Offline') DEFAULT 'Offline',
    active_snapshot_id INT,
    health_score INT DEFAULT 100, # PC 건강 상태 점수
    FOREIGN KEY (location_id) REFERENCES Location(location_id)
);

# 복구 시점 저장 테이블
CREATE TABLE Snapshot (
    snapshot_id INT AUTO_INCREMENT PRIMARY KEY,
    pc_id INT,
    slot_number TINYINT CHECK (slot_number BETWEEN 0 AND 4),
    description VARCHAR(50),
    created_at DATETIME DEFAULT NOW(),
    FOREIGN KEY (pc_id) REFERENCES PC(pc_id) ON DELETE CASCADE
);

# 설치된 소프트웨어 이력 테이블
CREATE TABLE Installed_Software (
    software_id INT AUTO_INCREMENT PRIMARY KEY,
    pc_id INT,
    software_name VARCHAR(100),
    install_date DATETIME DEFAULT NOW(),
    FOREIGN KEY (pc_id) REFERENCES PC(pc_id) ON DELETE CASCADE
);

# 시스템 감사 로그 테이블
CREATE TABLE Event_Log (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    event_time DATETIME DEFAULT NOW(),
    event_type VARCHAR(30),
    pc_id INT,
    details TEXT,
    FOREIGN KEY (pc_id) REFERENCES PC(pc_id) ON DELETE SET NULL
);

# PC 상세 정보 통합 뷰
CREATE OR REPLACE VIEW View_PC_Full_Info AS
SELECT 
    p.pc_id, p.pc_name, p.ip_address, p.current_mode, p.status, p.active_snapshot_id,
    p.health_score,
    l.floor, l.location_name,
    s.description AS active_snapshot_name, 
    s.created_at as snapshot_time,
    (SELECT COUNT(*) FROM Installed_Software sw WHERE sw.pc_id = p.pc_id) as sw_count
FROM PC p
LEFT JOIN Location l ON p.location_id = l.location_id
LEFT JOIN Snapshot s ON p.active_snapshot_id = s.snapshot_id;

# 특정 PC의 설치된 소프트웨어 개수 반환 함수
DELIMITER //
CREATE FUNCTION fn_GetSoftwareCount(f_pc_id INT) RETURNS INT
DETERMINISTIC
BEGIN
    DECLARE cnt INT;
    SELECT COUNT(*) INTO cnt FROM Installed_Software WHERE pc_id = f_pc_id;
    RETURN cnt;
END //
DELIMITER ;

# procedure 정의
DELIMITER //

# 신규 PC 등록 및 초기 스냅샷 자동 생성
CREATE PROCEDURE sp_RegisterPC(
    IN p_pc_name VARCHAR(50),
    IN p_location_id INT,
    IN p_ip_address VARCHAR(15),
    OUT p_result VARCHAR(100)
)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_result = 'Error: Registration Failed';
    END;

    START TRANSACTION;
        INSERT INTO PC (pc_name, location_id, ip_address, status, current_mode)
        VALUES (p_pc_name, p_location_id, p_ip_address, 'Offline', 'Recovery');
        
        SET @new_id = LAST_INSERT_ID();
        
        INSERT INTO Snapshot (pc_id, slot_number, description) 
        VALUES (@new_id, 0, '초기 시점');
        
        UPDATE PC SET active_snapshot_id = LAST_INSERT_ID() WHERE pc_id = @new_id;
        
        SET p_result = 'Success';
    COMMIT;
END //

# PC 모드 변경 및 로그 기록
CREATE PROCEDURE sp_ChangePCMode(
    IN p_pc_id INT,
    IN p_new_mode VARCHAR(20),
    IN p_admin_id INT,
    OUT p_result VARCHAR(100)
)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_result = 'Error: Mode Change Failed';
    END;

    START TRANSACTION;
        UPDATE PC SET current_mode = p_new_mode WHERE pc_id = p_pc_id;
        
        INSERT INTO Event_Log (event_type, pc_id, details)
        VALUES ('Mode_Change', p_pc_id, CONCAT('Admin changed mode to ', p_new_mode));
        
        SET p_result = 'Success';
    COMMIT;
END //

# 복구 시점 생성 및 갱신
CREATE PROCEDURE sp_CreateSnapshot(
    IN p_pc_id INT,
    IN p_slot_number INT,
    IN p_description VARCHAR(50)
)
BEGIN
    START TRANSACTION;
        DELETE FROM Snapshot WHERE pc_id = p_pc_id AND slot_number = p_slot_number;
        INSERT INTO Snapshot (pc_id, slot_number, description)
        VALUES (p_pc_id, p_slot_number, p_description);
    COMMIT;
END //

# 시스템 종료 시 모드에 따른 데이터 처리
CREATE PROCEDURE sp_ClientShutdownProcess(
    IN p_pc_id INT,
    OUT p_msg VARCHAR(255)
)
BEGIN
    DECLARE v_mode VARCHAR(20);
    DECLARE v_snap_time DATETIME;
    DECLARE v_del_count INT DEFAULT 0;

    START TRANSACTION; # ACID 보장
        
        SELECT p.current_mode, s.created_at INTO v_mode, v_snap_time
        FROM PC p LEFT JOIN Snapshot s ON p.active_snapshot_id = s.snapshot_id
        WHERE p.pc_id = p_pc_id
        FOR UPDATE; 

        # 고립성
        IF v_mode = 'Recovery' AND v_snap_time IS NOT NULL THEN
            DELETE FROM Installed_Software 
            WHERE pc_id = p_pc_id AND install_date > v_snap_time;
            
            SET v_del_count = ROW_COUNT();
            SET p_msg = CONCAT('System Rolled Back (Removed ', v_del_count, ' apps).');
        ELSE
            SET p_msg = 'Changes Saved (Maintenance Mode).';
        END IF;

        # 상태 변경
        UPDATE PC SET status = 'Offline' WHERE pc_id = p_pc_id;
        
        # 로그 기록
        INSERT INTO Event_Log (event_type, pc_id, details) VALUES ('Shutdown', p_pc_id, p_msg);
        
    COMMIT; # Durability 보장 (커밋된 내용은 영구 저장)
END //

# 야간 자동 유지보수 procedure
CREATE PROCEDURE sp_NightlyMaintenance()
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE v_pc_id INT;
    
    # Recovery 모드인 PC들만 선택하여 커서 생성
    DECLARE cur_pc CURSOR FOR 
        SELECT pc_id FROM PC WHERE current_mode = 'Recovery';
    
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

    OPEN cur_pc;
    
    read_loop: LOOP
        FETCH cur_pc INTO v_pc_id;
        IF done THEN
            LEAVE read_loop;
        END IF;
        
        CALL sp_ClientShutdownProcess(v_pc_id, @dummy_msg);
        
        INSERT INTO Event_Log (event_type, pc_id, details)
        VALUES ('Auto_Maintenance', v_pc_id, 'Nightly Auto Reset Completed');
        
    END LOOP;

    CLOSE cur_pc;
END //

# PC 건강 상태 점수 계산 procedure
CREATE PROCEDURE sp_CalculateHealthScore()
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE v_pc_id INT;
    DECLARE v_error_count INT;
    DECLARE v_sw_count INT;
    DECLARE v_score INT;
    
    # 모든 PC를 순회하는 커서
    DECLARE cur_health CURSOR FOR SELECT pc_id FROM PC;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;
    
    OPEN cur_health;
    
    read_loop: LOOP
        FETCH cur_health INTO v_pc_id;
        IF done THEN
            LEAVE read_loop;
        END IF;
        
        SET v_score = 100; # 기본 점수 100점에서 시작
        
        # 감점 요인 1: 최근 7일간 에러 로그 발생 횟수
        SELECT COUNT(*) INTO v_error_count 
        FROM Event_Log 
        WHERE pc_id = v_pc_id 
          AND (details LIKE '%Error%' OR event_type = 'Force_Shutdown')
          AND event_time > DATE_SUB(NOW(), INTERVAL 7 DAY);
        
        SET v_score = v_score - (v_error_count * 10);
        
        # 감점 요인 2: 소프트웨어가 너무 많이 설치됨
        SELECT fn_GetSoftwareCount(v_pc_id) INTO v_sw_count;
        IF v_sw_count > 10 THEN
            SET v_score = v_score - 5;
        END IF;
        
        IF v_score < 0 THEN SET v_score = 0; END IF; # 점수 보정
        
        UPDATE PC SET health_score = v_score WHERE pc_id = v_pc_id;
        
    END LOOP;
    
    CLOSE cur_health;
END //

DELIMITER ;

# 이벤트 스케줄러 활성화 및 등록
SET GLOBAL event_scheduler = ON;

CREATE EVENT ev_NightlyReset
ON SCHEDULE EVERY 1 DAY
STARTS '2025-01-01 23:00:00'
DO
    CALL sp_NightlyMaintenance();

# 소프트웨어 설치 감지 트리거
DELIMITER //
CREATE TRIGGER trg_AfterInstall
AFTER INSERT ON Installed_Software
FOR EACH ROW
BEGIN
    INSERT INTO Event_Log (event_type, pc_id, details)
    VALUES ('SW_Install', NEW.pc_id, CONCAT('Installed: ', NEW.software_name));
END //
DELIMITER ;

# 기초 데이터 삽입
INSERT INTO Location (floor, location_name) VALUES 
('B2', ''), # 지하 2층
('B1', ''), # 지하 1층
('1', ''), # 1층
('3', ''), # 3층
('IFZONE', ''), # IFZONE
('IFZONE', 'TROOM'); # IFZONE - TROOM
INSERT INTO Admin (username, password_hash, name) VALUES ('admin', 'pbkdf2:dummyhash', '관리자');