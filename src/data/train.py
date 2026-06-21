import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest

# Giả sử df là bảng dữ liệu bro vừa in ra
# Bước 1: Đặt cột 'node' làm chỉ mục (Index)
df = pd.read_csv('src/data/rogue_features.csv')

if 'node' in df.columns:
    df = df.set_index('node')

# Bước 2: Tách lấy các cột đặc trưng toán học (Bỏ cột role đi)
features = ['degree_centrality', 'betweenness_centrality', 'closeness_centrality', 'clustering_coefficient']
df_train = df[features]

# Bước 3: Chuẩn hóa dữ liệu (Z-score normalization)
scaler = StandardScaler()
X_scaled = scaler.fit_transform(df_train)

# Bước 4: Khởi tạo và huấn luyện mô hình
# Tham số contamination bro set bằng tỷ lệ số node lỗi / tổng số node (Ví dụ: 8/267 ≈ 0.03)
iso_forest = IsolationForest(n_estimators=100, contamination=0.03, random_state=42)

# Fit và dự đoán trực tiếp (1 là bình thường, -1 là bất thường)
df['anomaly_label'] = iso_forest.fit_predict(X_scaled)

# Bước 5: Trích xuất kết quả xuất sắc của bro
anomalies = df[df['anomaly_label'] == -1]

# Danh sách các Role được miễn trừ (Whitelist) vì bản chất toán học của chúng là Outliers
whitelisted_roles = ['Core Switch', 'Distribution Switch']

# Lọc bỏ các thiết bị nằm trong Whitelist
true_anomalies = anomalies[~anomalies['role'].isin(whitelisted_roles)]

print("--- CÁC THIẾT BỊ LẠ BỊ AI PHÁT HIỆN ---")
print(true_anomalies[['role', 'anomaly_label']])