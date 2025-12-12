from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
from werkzeug.security import check_password_hash
from functools import wraps
import datetime

app = Flask(__name__)
app.secret_key = 'super_secret_key'

# 초기 아이디 : admin, 비밀번호 : 1234
# 데이터베이스 연결 정보 설정
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'dlsnfl0615@',
    'database': 'netclass_db'
}

# DB 연결 객체 반환 함수
def get_db_connection():
    return mysql.connector.connect(**db_config)

# 관리자 세션 확인 데코레이터
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('관리자 로그인이 필요합니다.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 관리자 로그인 처리
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Admin WHERE username = %s", (username,))
        admin = cursor.fetchone()
        cursor.close()
        conn.close()

        # 해시 비밀번호 검증 및 백도어 허용
        if admin and (check_password_hash(admin['password_hash'], password) or password == '1234'): 
            session['admin_id'] = admin['admin_id']
            session['admin_name'] = admin['name']
            return redirect(url_for('index'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
    return render_template('login.html')

# 관리자 로그아웃 처리
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# 메인 대시보드 및 PC 목록 조회
@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM View_PC_Full_Info ORDER BY pc_id")
    pcs = cursor.fetchall()
    cursor.execute("SELECT * FROM Location")
    locations = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('index.html', pcs=pcs, locations=locations)

# 신규 PC 등록 및 procedure 호출
@app.route('/pc/register', methods=['GET', 'POST'])
@login_required
def register_pc():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        pc_name = request.form['pc_name']
        location_id = request.form['location_id']
        ip_address = request.form['ip_address']
        
        # 등록 procedure 실행 및 결과 메시지 확인
        args = [pc_name, location_id, ip_address, '']
        result_args = cursor.callproc('sp_RegisterPC', args)
        
        msg = result_args[3]
        conn.commit()
        
        if msg == 'Success':
            flash(f'PC [{pc_name}] 등록 및 초기화 완료', 'success')
            return redirect(url_for('index'))
        else:
            flash(msg, 'danger')

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Location")
    locations = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('register_pc.html', locations=locations)

# PC 관리 모드 변경
@app.route('/change_mode', methods=['POST'])
@login_required
def change_mode():
    pc_id = request.form['pc_id']
    new_mode = request.form['new_mode']
    admin_id = session['admin_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.callproc('sp_ChangePCMode', [pc_id, new_mode, admin_id, ''])
        conn.commit()
        flash(f'PC {pc_id}번 모드 변경 완료: {new_mode}', 'success')
    except Exception as e:
        flash(f'오류: {e}', 'danger')
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

# PC 상세 정보 및 스냅샷 내역 조회
@app.route('/pc/<int:pc_id>')
@login_required
def pc_detail(pc_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM View_PC_Full_Info WHERE pc_id = %s", (pc_id,))
    pc = cursor.fetchone()
    
    cursor.execute("SELECT * FROM Snapshot WHERE pc_id = %s ORDER BY slot_number", (pc_id,))
    snapshots = cursor.fetchall()
    cursor.execute("SELECT * FROM Installed_Software WHERE pc_id = %s ORDER BY install_date DESC", (pc_id,))
    softwares = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('pc_detail.html', pc=pc, snapshots=snapshots, softwares=softwares)

# 복구용 스냅샷 생성
@app.route('/pc/create_snapshot', methods=['POST'])
@login_required
def create_snapshot():
    pc_id = request.form['pc_id']
    slot = request.form['slot_number']
    desc = request.form['description']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.callproc('sp_CreateSnapshot', [pc_id, slot, desc])
    
    conn.commit()
    cursor.close()
    conn.close()
    flash('새 복구 시점이 생성되었습니다.', 'success')
    return redirect(url_for('pc_detail', pc_id=pc_id))

# 복구 기준 시점 변경
@app.route('/pc/set_active_snapshot', methods=['POST'])
@login_required
def set_active_snapshot():
    pc_id = request.form['pc_id']
    snapshot_id = request.form['snapshot_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE PC SET active_snapshot_id = %s WHERE pc_id = %s", (snapshot_id, pc_id))
    conn.commit()
    cursor.close()
    conn.close()
    flash('복구 기준 시점이 변경되었습니다.', 'success')
    return redirect(url_for('pc_detail', pc_id=pc_id))

# 고급 SQL 기능을 활용한 통계 페이지
@app.route('/analytics')
@login_required
def analytics():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 윈도우 함수를 이용한 설치 빈도 순위
    cursor.execute("""
        SELECT p.pc_name, COUNT(s.software_id) as cnt,
               DENSE_RANK() OVER (ORDER BY COUNT(s.software_id) DESC) as ranking
        FROM PC p LEFT JOIN Installed_Software s ON p.pc_id = s.pc_id 
        GROUP BY p.pc_id
    """)
    rankings = cursor.fetchall()

    # 롤업을 이용한 위치별 PC 대수 소계
    cursor.execute("""
        SELECT 
            IFNULL(l.floor, 'Total') as floor_grp, 
            CASE 
                WHEN l.location_name IS NULL THEN 'Sub Total'
                WHEN l.location_name = '' THEN '일반 구역'
                ELSE l.location_name
            END as loc_grp, 
            COUNT(p.pc_id) as pc_count
        FROM Location l LEFT JOIN PC p ON l.location_id = p.location_id
        GROUP BY l.floor, l.location_name WITH ROLLUP
    """)
    rollups = cursor.fetchall()
    
    # 함수를 이용한 소프트웨어 카운트
    cursor.execute("SELECT pc_name, fn_GetSoftwareCount(pc_id) as sw_count FROM PC")
    sw_counts = cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('analytics.html', sw_counts=sw_counts, rankings=rankings, rollups=rollups)

# 클라이언트 시뮬레이션 PC 선택
@app.route('/client')
def client_select():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM View_PC_Full_Info ORDER BY pc_id")
    pcs = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('client_select.html', pcs=pcs)

# 클라이언트 데스크톱 화면 및 상태 업데이트
@app.route('/client/<int:pc_id>')
def client_desktop(pc_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM View_PC_Full_Info WHERE pc_id = %s", (pc_id,))
    pc = cursor.fetchone()
    
    cursor.execute("SELECT * FROM Installed_Software WHERE pc_id = %s ORDER BY install_date DESC", (pc_id,))
    softwares = cursor.fetchall()
    
    cursor.execute("UPDATE PC SET status='Online' WHERE pc_id=%s", (pc_id,))
    conn.commit()
    
    cursor.close()
    conn.close()
    return render_template('client_desktop.html', pc=pc, softwares=softwares)

# 소프트웨어 설치 시뮬레이션
@app.route('/client/install', methods=['POST'])
def client_install():
    pc_id = request.form['pc_id']
    software_name = request.form['software_name']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO Installed_Software (pc_id, software_name, install_date) VALUES (%s, %s, NOW())", 
                   (pc_id, software_name))
    conn.commit()
    cursor.close()
    conn.close()
    flash(f'[{software_name}] 설치가 완료되었습니다.', 'success')
    return redirect(url_for('client_desktop', pc_id=pc_id))

# 클라이언트 종료 및 복구 처리
@app.route('/client/shutdown', methods=['POST'])
def client_shutdown():
    pc_id = request.form['pc_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    args = [pc_id, '']
    result = cursor.callproc('sp_ClientShutdownProcess', args)
    
    db_message = result[1]
    conn.commit()
    cursor.close()
    conn.close()
    
    flash(f'시스템 종료: {db_message}', 'info')
    return redirect(url_for('client_select'))

# 관리자 원격 명령 수행
@app.route('/remote_command', methods=['POST'])
@login_required
def remote_command():
    target_pc_id = request.form['target_pc_id']
    command_type = request.form['command_type']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 강제 로그오프 및 종료 처리
        if command_type == 'Logoff':
            args = [target_pc_id, '']
            result = cursor.callproc('sp_ClientShutdownProcess', args)
            db_msg = result[1]
            
            cursor.execute("""
                INSERT INTO Event_Log (event_type, pc_id, details)
                VALUES ('Remote_Shutdown', %s, CONCAT('Admin forced shutdown: ', %s))
            """, (target_pc_id, db_msg))
            flash(f'원격 시스템 종료 완료: {db_msg}', 'success')

        # 재부팅 명령 처리
        elif command_type == 'Restart':
             args = [target_pc_id, '']
             result = cursor.callproc('sp_ClientShutdownProcess', args)
             db_msg = result[1]
             cursor.execute("""
                INSERT INTO Event_Log (event_type, pc_id, details)
                VALUES ('Remote_Restart', %s, %s)
            """, (target_pc_id, db_msg))
             flash(f'재부팅 명령 전송: {db_msg}', 'success')

        # 기타 명령 처리
        else:
            cursor.execute("""
                INSERT INTO Event_Log (event_type, pc_id, details)
                VALUES ('Remote_Command', %s, CONCAT('Admin sent command: ', %s))
            """, (target_pc_id, command_type))
            flash(f'명령 전송 성공: {command_type}', 'success')
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        flash(f'명령 처리 실패: {e}', 'danger')
        
    cursor.close()
    conn.close()
    
    return redirect(url_for('pc_detail', pc_id=target_pc_id))

# PC 건강 상태 수동 점검
@app.route('/admin/health_check', methods=['POST'])
@login_required
def health_check():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.callproc('sp_CalculateHealthScore')
        conn.commit()
        flash('전체 PC 건강 상태 점검이 완료되었습니다.', 'success')
    except Exception as e:
        flash(f'점검 실패: {e}', 'danger')
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

# 야간 유지보수 강제 실행
@app.route('/admin/run_maintenance', methods=['POST'])
@login_required
def run_maintenance():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.callproc('sp_NightlyMaintenance')
        conn.commit()
        flash('야간 유지보수 작업이 강제로 실행되었습니다.', 'info')
    except Exception as e:
        flash(f'작업 실패: {e}', 'danger')
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

# 시스템 이벤트 로그 조회
@app.route('/logs')
@login_required
def view_logs():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT l.log_id, l.event_time, l.event_type, l.details, p.pc_name 
        FROM Event_Log l 
        LEFT JOIN PC p ON l.pc_id = p.pc_id 
        ORDER BY l.event_time DESC
        LIMIT 100
    """
    cursor.execute(query)
    logs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return render_template('logs.html', logs=logs)

if __name__ == '__main__':
    app.run(debug=True, port=5000)