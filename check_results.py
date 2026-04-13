import sqlite3

conn = sqlite3.connect('portal.db')
cursor = conn.cursor()

# 检查错误日志数量
cursor.execute('SELECT COUNT(*) FROM registration_logs WHERE level = "error"')
error_count = cursor.fetchone()[0]
print(f'错误日志数量: {error_count}')

# 检查一个错误消息
if error_count > 0:
    cursor.execute('SELECT message FROM registration_logs WHERE level = "error" LIMIT 1')
    error_msg = cursor.fetchone()[0]
    print(f'示例错误: {error_msg[:200]}...')

conn.close()