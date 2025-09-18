# streamlit_barcode_health_app.py
# Streamlit app: "Scanner Saudável" - Escaneie código de barras e verifique qualidade nutricional
#streamlit run barcode_health_app.py

import streamlit as st
import sqlite3
import pandas as pd
import io
from PIL import Image
import datetime
import altair as alt
import requests
import os

# --- Instalação de bibliotecas (opcional, Streamlit Cloud gerencia) ---
try:
    from pyzbar.pyzbar import decode
    PYZBAR_AVAILABLE = True
except Exception:
    PYZBAR_AVAILABLE = False

# --- CONFIGURAÇÃO E DADOS ---
# ALERTA: Substitua esta URL pela URL "Raw" do seu arquivo products.db no GitHub
GITHUB_DB_URL = "https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPOSITORIO/main/products.db"
DB_PATH = "products.db"

NUTRI_PASSWORD = "nutri123"

# Dados de exemplo para o caso de o banco de dados estar vazio
# (Este bloco pode ser removido se o products.db estiver sempre preenchido)
SAMPLE_CSV_DATA = """
barcode,name,brand,category,sodium_mg_per_100g,sugar_g_per_100g,total_fat_g_per_100g,is_gmo
7891234567890,Suco de Uva Integral,Vinhedo Bom,Bebidas,5,15,0.1,Não
7890000000000,Biscoito Recheado,Sabor Doce,Lanches,250,30,15,Sim
7891111111111,Iogurte Natural,Lácteos Saudáveis,Laticínios,80,5,3,Não
"""

# --- FUNÇÕES DE BANCO DE DADOS E LÓGICA ---

def download_db_from_github():
    """Faz o download do banco de dados do GitHub."""
    st.info("Baixando o banco de dados do GitHub...")
    try:
        response = requests.get(GITHUB_DB_URL)
        response.raise_for_status()  # Levanta um erro se a requisição falhar
        with open(DB_PATH, "wb") as f:
            f.write(response.content)
        st.success("Banco de dados baixado com sucesso!")
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao baixar o banco de dados do GitHub. Verifique a URL: {GITHUB_DB_URL}")
        st.error(f"Detalhes do erro: {e}")
        st.stop()  # Interrompe a execução em caso de falha grave

@st.cache_resource
def init_db():
    """Conecta ou inicializa o banco de dados."""
    if not os.path.exists(DB_PATH):
        download_db_from_github()
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS products (
            barcode TEXT PRIMARY KEY,
            name TEXT,
            brand TEXT,
            category TEXT,
            sodium_mg_per_100g REAL,
            sugar_g_per_100g REAL,
            total_fat_g_per_100g REAL,
            is_gmo TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS consumption (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            barcode TEXT,
            timestamp DATETIME,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (barcode) REFERENCES products(barcode)
        )
    ''')
    conn.commit()

    # Verifica se a tabela 'products' está vazia e preenche se necessário
    cur.execute('SELECT COUNT(*) FROM products')
    if cur.fetchone()[0] == 0:
        st.warning("Banco de dados 'products' está vazio. Preenchendo com dados de exemplo...")
        df = pd.read_csv(io.StringIO(SAMPLE_CSV_DATA))
        df.to_sql('products', conn, if_exists='append', index=False)
        st.success("Dados de exemplo carregados.")

    return conn

def get_product_by_barcode(conn, barcode):
    df = pd.read_sql_query('SELECT * FROM products WHERE barcode = ?', conn, params=(barcode,))
    if df.empty:
        return None
    return df.iloc[0].to_dict()

def add_product(conn, data):
    cur = conn.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO products (barcode, name, brand, category, sodium_mg_per_100g, sugar_g_per_100g, total_fat_g_per_100g, is_gmo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (data['barcode'], data['name'], data['brand'], data['category'], data['sodium_mg_per_100g'], data['sugar_g_per_100g'], data['total_fat_g_per_100g'], data['is_gmo']))
    conn.commit()

def get_user_id(conn, username):
    cur = conn.cursor()
    cur.execute('INSERT OR IGNORE INTO users (username) VALUES (?)', (username,))
    conn.commit()
    cur.execute('SELECT id FROM users WHERE username = ?', (username,))
    return cur.fetchone()[0]

def add_consumption(conn, user_id, barcode):
    cur = conn.cursor()
    cur.execute('INSERT INTO consumption (user_id, barcode, timestamp) VALUES (?, ?, ?)',
                (user_id, barcode, datetime.datetime.now()))
    conn.commit()

def get_user_consumption(conn, user_id):
    query = '''
        SELECT c.timestamp, p.name, p.brand, p.category, p.sodium_mg_per_100g, p.sugar_g_per_100g, p.total_fat_g_per_100g, p.is_gmo
        FROM consumption c
        JOIN products p ON c.barcode = p.barcode
        WHERE c.user_id = ?
        ORDER BY c.timestamp DESC
    '''
    df = pd.read_sql_query(query, conn, params=(user_id,))
    return df

def get_nutri_consumption(conn):
    query = '''
        SELECT c.timestamp, u.username, p.name, p.brand, p.category, p.sodium_mg_per_100g, p.sugar_g_per_100g, p.total_fat_g_per_100g, p.is_gmo
        FROM consumption c
        JOIN products p ON c.barcode = p.barcode
        JOIN users u ON c.user_id = u.id
        ORDER BY c.timestamp DESC
    '''
    df = pd.read_sql_query(query, conn)
    return df

def compute_health_score(sodium, sugar, fat, is_gmo):
    score = 100
    if sodium > 400: score -= 20
    elif sodium > 200: score -= 10

    if sugar > 20: score -= 20
    elif sugar > 10: score -= 10
    
    if fat > 10: score -= 20
    elif fat > 5: score -= 10
    
    if is_gmo == "Sim": score -= 15

    return max(0, score)

def score_label(score):
    if score >= 80: return "Bom"
    if score >= 50: return "Médio"
    return "Ruim"

# --- APLICAÇÃO STREAMLIT PRINCIPAL ---

st.set_page_config(page_title='Scanner Saudável', layout='wide')
st.title('Scanner Saudável 🥦📱')

# Inicializa o banco de dados (e baixa se não existir)
conn = init_db()

if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'username' not in st.session_state:
    st.session_state.username = None

def login_user():
    st.session_state.user_id = get_user_id(conn, st.session_state.username)

# --- Autenticação do Usuário ---
if st.session_state.user_id is None:
    username = st.text_input("Digite seu nome de usuário para começar:")
    if st.button("Entrar"):
        if username:
            st.session_state.username = username.strip()
            login_user()
            st.rerun()
        else:
            st.warning("Por favor, digite um nome de usuário.")
    st.stop()

# --- Menu Principal ---
st.sidebar.header(f"Bem-vindo, {st.session_state.username}!")
menu = st.sidebar.radio("Navegação", ["Consulta", "Cadastrar Novo Produto", "Meu Histórico", "Painel do Nutricionista"])

# --- Página de Consulta ---
if menu == "Consulta":
    st.header("🔍 Consulta de Produtos")
    
    barcode_input = st.text_input("Digite o código de barras:")
    uploaded_image = st.file_uploader("Ou faça upload de uma foto do código de barras:", type=["jpg", "jpeg", "png"])
    
    barcode = barcode_input.strip()
    
    if uploaded_image and PYZBAR_AVAILABLE:
        image = Image.open(uploaded_image)
        barcodes = decode(image)
        if barcodes:
            barcode = barcodes[0].data.decode('utf-8')
            st.info(f"Código de barras detectado: {barcode}")
        else:
            st.error("Nenhum código de barras detectado na imagem.")

    if barcode:
        product_data = get_product_by_barcode(conn, barcode)
        if product_data:
            st.subheader(f"✅ Produto Encontrado: {product_data['name']}")
            st.write(f"**Marca:** {product_data['brand']}")
            
            # Cálculo e exibição do score
            score = compute_health_score(
                product_data['sodium_mg_per_100g'],
                product_data['sugar_g_per_100g'],
                product_data['total_fat_g_per_100g'],
                product_data['is_gmo']
            )
            label = score_label(score)
            
            if label == "Bom":
                st.success(f"Qualidade Nutricional: **{label}**")
            elif label == "Médio":
                st.warning(f"Qualidade Nutricional: **{label}**")
            else:
                st.error(f"Qualidade Nutricional: **{label}**")
            
            # Tabela de detalhes
            details = {
                "Sódio": f"{product_data['sodium_mg_per_100g']} mg/100g",
                "Açúcar": f"{product_data['sugar_g_per_100g']} g/100g",
                "Gordura Total": f"{product_data['total_fat_g_per_100g']} g/100g",
                "Transgênico": product_data['is_gmo']
            }
            st.table(pd.DataFrame(details.items(), columns=["Nutriente", "Valor"]))
            
            if st.button("Validar Consumo"):
                add_consumption(conn, st.session_state.user_id, barcode)
                st.success(f"Consumo de '{product_data['name']}' registrado com sucesso!")

        else:
            st.warning("Produto não encontrado no banco de dados. Gostaria de adicioná-lo?")
            if st.button("Cadastrar Novo Produto"):
                st.session_state.menu = "Cadastrar Novo Produto"
                st.experimental_rerun()

# --- Página de Cadastrar Novo Produto ---
elif menu == "Cadastrar Novo Produto":
    st.header("📝 Cadastrar Novo Produto")
    
    with st.form("new_product_form"):
        new_barcode = st.text_input("Código de Barras", placeholder="Ex: 7891234567890")
        new_name = st.text_input("Nome do Produto")
        new_brand = st.text_input("Marca")
        new_category = st.selectbox("Categoria", ["Lanches", "Bebidas", "Laticínios", "Outros"])
        new_sodium = st.number_input("Sódio (mg por 100g)", min_value=0.0)
        new_sugar = st.number_input("Açúcar (g por 100g)", min_value=0.0)
        new_fat = st.number_input("Gordura Total (g por 100g)", min_value=0.0)
        new_gmo = st.selectbox("Contém Transgênico?", ["Não", "Sim"])
        
        submitted = st.form_submit_button("Cadastrar")
        if submitted:
            if new_barcode and new_name and new_brand:
                new_product = {
                    'barcode': new_barcode,
                    'name': new_name,
                    'brand': new_brand,
                    'category': new_category,
                    'sodium_mg_per_100g': new_sodium,
                    'sugar_g_per_100g': new_sugar,
                    'total_fat_g_per_100g': new_fat,
                    'is_gmo': new_gmo
                }
                add_product(conn, new_product)
                st.success(f"Produto '{new_name}' cadastrado com sucesso!")
                st.info("Você pode ir para a página de 'Consulta' para usá-lo.")
            else:
                st.error("Por favor, preencha todos os campos obrigatórios.")

# --- Página Meu Histórico ---
elif menu == "Meu Histórico":
    st.header("⏳ Meu Histórico de Consumo")
    consumption_df = get_user_consumption(conn, st.session_state.user_id)
    
    if consumption_df.empty:
        st.info("Você ainda não validou nenhum consumo. Use a página 'Consulta' para começar!")
    else:
        st.subheader("Itens Consumidos")
        st.dataframe(consumption_df[['timestamp', 'name', 'brand', 'sodium_mg_per_100g', 'sugar_g_per_100g', 'total_fat_g_per_100g', 'is_gmo']].set_index('timestamp'))

        st.subheader("Visão Geral do Seu Consumo")
        st.bar_chart(consumption_df['category'].value_counts())
        
        # Gráfico de pizza com avaliação de saúde
        consumption_df['score'] = consumption_df.apply(
            lambda row: compute_health_score(row['sodium_mg_per_100g'], row['sugar_g_per_100g'], row['total_fat_g_per_100g'], row['is_gmo']), axis=1
        )
        consumption_df['label'] = consumption_df['score'].apply(score_label)
        
        st.subheader("Qualidade Nutricional do Seu Consumo")
        label_counts = consumption_df['label'].value_counts().reset_index()
        label_counts.columns = ['label', 'count']
        
        pie_chart = alt.Chart(label_counts).mark_arc(outerRadius=120).encode(
            theta=alt.Theta("count", stack=True),
            color=alt.Color("label", sort=["Bom", "Médio", "Ruim"], scale=alt.Scale(domain=["Bom", "Médio", "Ruim"], range=["#34a853", "#fbbc05", "#ea4335"])),
            order=alt.Order("count", sort="descending"),
            tooltip=["label", "count"]
        ).properties(
            title="Distribuição da Qualidade dos Itens Consumidos"
        )
        
        st.altair_chart(pie_chart, use_container_width=True)

# --- Página Painel do Nutricionista ---
elif menu == "Painel do Nutricionista":
    st.header("👨‍⚕️ Painel do Nutricionista")
    password = st.text_input("Digite a senha para acesso:", type="password")
    
    if password == NUTRI_PASSWORD:
        st.success("Acesso concedido!")
        
        nutri_df = get_nutri_consumption(conn)
        if nutri_df.empty:
            st.info("Ainda não há dados de consumo registrados pelos usuários.")
        else:
            st.subheader("Histórico de Consumo Geral dos Usuários")
            st.dataframe(nutri_df.set_index('timestamp'))
            
            st.subheader("Análise por Usuário")
            users = nutri_df['username'].unique()
            selected_user = st.selectbox("Selecione um usuário:", users)
            
            user_specific_df = nutri_df[nutri_df['username'] == selected_user]
            
            st.subheader(f"Consumo de {selected_user}")
            st.bar_chart(user_specific_df['category'].value_counts())
            
            user_specific_df['score'] = user_specific_df.apply(
                lambda row: compute_health_score(row['sodium_mg_per_100g'], row['sugar_g_per_100g'], row['total_fat_g_per_100g'], row['is_gmo']), axis=1
            )
            user_specific_df['label'] = user_specific_df['score'].apply(score_label)
            
            label_counts_user = user_specific_df['label'].value_counts().reset_index()
            label_counts_user.columns = ['label', 'count']
            
            pie_chart_user = alt.Chart(label_counts_user).mark_arc(outerRadius=120).encode(
                theta=alt.Theta("count", stack=True),
                color=alt.Color("label", sort=["Bom", "Médio", "Ruim"], scale=alt.Scale(domain=["Bom", "Médio", "Ruim"], range=["#34a853", "#fbbc05", "#ea4335"])),
                order=alt.Order("count", sort="descending"),
                tooltip=["label", "count"]
            ).properties(
                title=f"Qualidade Nutricional do Consumo de {selected_user}"
            )
            
            st.altair_chart(pie_chart_user, use_container_width=True)
            
    elif password:
        st.error("Senha incorreta.")