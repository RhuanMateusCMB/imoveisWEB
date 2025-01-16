import streamlit as st
import pandas as pd
import time
import random
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import traceback
from supabase import create_client, Client
from decimal import Decimal

# Configuração do tema e estilo da página
st.set_page_config(
    page_title="Coletor de Dados Imobiliários - Eusébio",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS permanece o mesmo...
st.markdown("""
    <style>
        .main {
            padding: 2rem;
        }
        .stProgress > div > div > div > div {
            background-color: #00a6ed;
        }
        .stButton > button {
            background-color: #00a6ed;
            color: white;
            border-radius: 5px;
            padding: 0.5rem 2rem;
            font-weight: 500;
        }
        .stButton > button:hover {
            background-color: #0090d1;
        }
        .status-container {
            background-color: #f0f2f6;
            padding: 1rem;
            border-radius: 5px;
            margin: 1rem 0;
        }
        .success-message {
            color: #28a745;
            padding: 1rem;
            border-radius: 5px;
            margin-top: 1rem;
        }
        .error-message {
            color: #dc3545;
            padding: 1rem;
            border-radius: 5px;
            margin-top: 1rem;
        }
    </style>
""", unsafe_allow_html=True)

# Inicialização do Supabase
try:
    supabase: Client = create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )
except Exception as e:
    st.error(f"Erro ao conectar com Supabase: {str(e)}")
    supabase = None

def converter_preco(valor):
    """Converte string de preço para float"""
    try:
        if isinstance(valor, str):
            valor_limpo = valor.replace('R$ ', '').replace('.', '').replace(',', '.')
            return float(valor_limpo)
        return float(valor)
    except:
        return 0.0

def converter_area(valor):
    """Extrai o número da string de área e converte para float"""
    try:
        if isinstance(valor, str):
            match = re.search(r'(\d+)', valor)
            if match:
                return float(match.group(1))
        return float(valor)
    except:
        return 0.0

def extrair_dados_html(html):
    """Extrai dados usando BeautifulSoup"""
    soup = BeautifulSoup(html, 'html.parser')
    dados = []
    
    cards = soup.find_all('div', {'data-qa': 'posting PROPERTY'})
    
    for card in cards:
        try:
            container = card.find('div', class_='postingCardLayout-module__posting-card-container__G_UsJ')
            if not container:
                continue
            
            card_id = card.get('data-id')
            
            preco_elem = container.find('div', {'data-qa': 'POSTING_CARD_PRICE'})
            preco = preco_elem.text.strip() if preco_elem else "0"
            
            endereco_elem = container.find('div', class_='postingLocations-module__location-address__k8Ip7')
            endereco = endereco_elem.text.strip() if endereco_elem else "Não informado"
            
            localidade_elem = container.find('h2', {'data-qa': 'POSTING_CARD_LOCATION'})
            localidade = localidade_elem.text.strip() if localidade_elem else "Não informado"
            
            area_elem = container.find('span', class_='postingMainFeatures-module__posting-main-features-span__ror2o')
            area = area_elem.text.strip() if area_elem else "0"
            
            link = card.get('data-to-posting')
            if link:
                link = f"https://www.imovelweb.com.br{link}"
            else:
                link = "Não informado"
            
            # Converter valores numéricos
            preco_decimal = converter_preco(preco)
            area_decimal = converter_area(area)
            
            dados.append({
                'cardid': card_id,
                'preco_real': float(preco_decimal),
                'endereco': endereco,
                'localidade': localidade,
                'area_m2': float(area_decimal),
                'link': link
            })
            
        except Exception as e:
            st.error(f"Erro ao extrair dados do card: {str(e)}")
            continue
            
    return dados

def inserir_dados_supabase(dados):
    """Insere dados no Supabase"""
    if not supabase:
        st.error("Conexão com Supabase não está disponível")
        return 0
        
    registros_inseridos = 0
    for registro in dados:
        try:
            dados_validados = {
                'cardID': str(registro['cardid']),
                'preco_Real': float(registro['preco_real']),
                'endereco': str(registro['endereco']),
                'localidade': str(registro['localidade']),
                'area_m2': float(registro['area_m2']),
                'link': str(registro['link'])
            }
            supabase.table('imoveisweb').insert([dados_validados]).execute()
            registros_inseridos += 1
        except Exception as e:
            st.error(f"Erro ao inserir registro: {str(e)}")
            continue
    return registros_inseridos

def coletar_dados_imoveis():
    # Cabeçalho
    st.title('🏠 Coletor de Dados Imobiliários - Eusébio')
    st.markdown("""
        <div style='margin-bottom: 2rem;'>
            Ferramenta automatizada para coleta de dados de terrenos à venda no Eusébio-CE.
            Os dados são atualizados em tempo real e armazenados de forma segura.
        </div>
    """, unsafe_allow_html=True)
    
    # Interface de configuração
    with st.container():
        col1, col2 = st.columns([3, 1])
        with col1:
            num_paginas = st.slider(
                'Selecione o número de páginas para análise',
                min_value=1,
                max_value=9,
                value=1,
                help='Quanto mais páginas, mais dados serão coletados'
            )
        with col2:
            iniciar_coleta = st.button('Iniciar Coleta', use_container_width=True)
    
    if iniciar_coleta:
        # Container para status e progresso
        status_container = st.container()
        with status_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
            info_col1, info_col2 = st.columns(2)
            
            with info_col1:
                terrenos_coletados = st.empty()
            with info_col2:
                tempo_estimado = st.empty()
        
        dados_total = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                
                # Lógica de coleta
                for pagina in range(num_paginas):
                    status_text.markdown(f"**Status:** Coletando dados da página {pagina + 1}...")
                    
                    url = f"https://www.imovelweb.com.br/terrenos-venda-eusebio-ce{'-pagina-' + str(pagina + 1) if pagina > 0 else ''}.html"
                    
                    try:
                        page.goto(url)
                        page.wait_for_load_state('networkidle')
                        
                        # Scroll da página
                        for _ in range(10):
                            page.mouse.wheel(0, 300)
                            time.sleep(0.3)
                        
                        dados_pagina = extrair_dados_html(page.content())
                        if dados_pagina:
                            dados_total.extend(dados_pagina)
                    except Exception as e:
                        st.error(f"Erro ao coletar dados da página {pagina + 1}: {str(e)}")
                    
                    # Atualizar interface
                    progress = (pagina + 1) / num_paginas
                    progress_bar.progress(progress)
                    terrenos_coletados.metric("Terrenos Encontrados", len(dados_total))
                    tempo_estimado.metric("Página Atual", f"{pagina + 1} de {num_paginas}")
                    
                    time.sleep(random.uniform(3, 6))
                
                browser.close()
            
            # Processar dados coletados
            if dados_total:
                status_text.markdown("**Status:** Salvando dados no banco...")
                registros_inseridos = inserir_dados_supabase(dados_total)
                
                if registros_inseridos > 0:
                    st.success(f'✅ Coleta finalizada com sucesso! {registros_inseridos} novos registros inseridos.')
                    
                    # Mostrar prévia dos dados
                    st.subheader('📊 Resumo dos Dados Coletados')
                    df_preview = pd.DataFrame(dados_total)
                    st.dataframe(
                        df_preview,
                        column_config={
                            "preco_real": st.column_config.NumberColumn("Preço (R$)", format="R$ %.2f"),
                            "area_m2": st.column_config.NumberColumn("Área (m²)", format="%.2f m²"),
                        },
                        hide_index=True
                    )
            else:
                st.warning('⚠️ Nenhum dado novo encontrado para coleta.')
                
        except Exception as e:
            st.error(f'❌ Ocorreu um erro durante a coleta: {str(e)}')
            st.error(traceback.format_exc())

if __name__ == "__main__":
    coletar_dados_imoveis()
