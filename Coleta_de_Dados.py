import streamlit as st
import pandas as pd
import time
import random
from datetime import datetime
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from supabase import create_client
import hashlib

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 8
    pausa_rolagem: int = 2
    espera_carregamento: int = 4
    url_base: str = "https://www.imovelweb.com.br/terrenos-venda-eusebio-ce.html"
    tentativas_max: int = 3

# Configuração da página Streamlit
st.set_page_config(
    page_title="CMB - Capital",
    page_icon="🏗️",
    layout="wide"
)

# Estilo CSS personalizado (mantido do arquivo original)
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        height: 3em;
        font-size: 20px;
    }
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .login-container {
        max-width: 400px;
        margin: auto;
        padding: 2rem;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        background-color: #1E1E1E;
        border: 1px solid #333;
    }
    /* [resto dos estilos mantidos como no original] */
    </style>
    """, unsafe_allow_html=True)

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def verificar_credenciais(self, email: str, senha: str) -> bool:
        try:
            senha_hash = hashlib.sha256(senha.encode()).hexdigest()
            response = self.supabase.table('usuarios').select('*').eq('email', email).execute()
            if response.data and len(response.data) > 0:
                usuario = response.data[0]
                return usuario['senha_hash'] == senha_hash
            return False
        except Exception as e:
            st.error(f"Erro ao verificar credenciais: {str(e)}")
            return False

    def inserir_dados(self, df):
        try:
            registros = []
            for _, row in df.iterrows():
                dados_validados = {
                    'cardID': str(row['cardid']),
                    'preco_Real': float(row['preco_real']),
                    'endereco': str(row['endereco']),
                    'localidade': str(row['localidade']),
                    'area_m2': float(row['area_m2']),
                    'link': str(row['link'])
                }
                registros.append(dados_validados)
            
            if registros:
                self.supabase.table('imoveisatual').insert(registros).execute()
            return len(registros)
        except Exception as e:
            st.error(f"Erro ao inserir dados: {str(e)}")
            return 0

class ScraperImovelWeb:
    def __init__(self, config: ConfiguracaoScraper):
        self.config = config
        self.logger = self._configurar_logger()

    @staticmethod
    def _configurar_logger() -> logging.Logger:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)

    def _get_random_user_agent(self):
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36'
        ]
        return random.choice(user_agents)

    def _configurar_navegador(self) -> webdriver.Chrome:
        try:
            opcoes_chrome = Options()
            opcoes_chrome.add_argument('--headless=new')
            opcoes_chrome.add_argument('--no-sandbox')
            opcoes_chrome.add_argument('--disable-dev-shm-usage')
            opcoes_chrome.add_argument('--window-size=1920,1080')
            opcoes_chrome.add_argument('--disable-blink-features=AutomationControlled')
            opcoes_chrome.add_argument('--enable-javascript')
            
            user_agent = self._get_random_user_agent()
            opcoes_chrome.add_argument(f'--user-agent={user_agent}')
            opcoes_chrome.add_argument('--accept-language=pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7')
            
            service = Service("/usr/bin/chromedriver")
            navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
            
            navegador.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": user_agent,
                "platform": "Windows NT 10.0; Win64; x64"
            })
            
            navegador.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return navegador
        except Exception as e:
            self.logger.error(f"Erro ao configurar navegador: {str(e)}")
            return None

    def _rolar_pagina(self, navegador: webdriver.Chrome) -> None:
        try:
            altura_total = navegador.execute_script("return document.body.scrollHeight")
            altura_atual = 0
            passo = altura_total / 4
            
            for _ in range(4):
                altura_atual += passo
                navegador.execute_script(f"window.scrollTo(0, {altura_atual});")
                time.sleep(random.uniform(0.5, 1.0))
                
            navegador.execute_script(f"window.scrollTo(0, {altura_total - 200});")
            time.sleep(1)
        except Exception as e:
            self.logger.error(f"Erro ao rolar página: {str(e)}")

    def _extrair_dados_html(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, 'html.parser')
        dados = []
        
        # Adaptado para o ImovelWeb
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
                
                dados.append({
                    'cardid': card_id,
                    'preco_real': self._converter_preco(preco),
                    'endereco': endereco,
                    'localidade': localidade,
                    'area_m2': self._converter_area(area),
                    'link': link,
                    'data_coleta': datetime.now().strftime("%Y-%m-%d")
                })
                
            except Exception as e:
                self.logger.error(f"Erro ao extrair dados do card: {str(e)}")
                continue
                
        return dados

    def _converter_preco(self, valor: str) -> float:
        try:
            if isinstance(valor, str):
                valor_limpo = valor.replace('R$ ', '').replace('.', '').replace(',', '.')
                return float(valor_limpo)
            return float(valor)
        except:
            return 0.0

    def _converter_area(self, valor: str) -> float:
        try:
            if isinstance(valor, str):
                valor_numerico = ''.join(filter(str.isdigit, valor))
                return float(valor_numerico) if valor_numerico else 0.0
            return float(valor)
        except:
            return 0.0

    def coletar_dados(self, num_paginas: int = 9) -> Optional[pd.DataFrame]:
        navegador = None
        todos_dados: List[Dict] = []
        progresso = st.progress(0)
        status = st.empty()
    
        try:
            navegador = self._configurar_navegador()
            if navegador is None:
                st.error("Não foi possível inicializar o navegador")
                return None

            for pagina in range(num_paginas):
                try:
                    status.text(f"⏳ Processando página {pagina + 1}/{num_paginas}")
                    progresso.progress((pagina + 1) / num_paginas)
                    
                    url = f"{self.config.url_base[:-5]}{'-pagina-' + str(pagina + 1) if pagina > 0 else ''}.html"
                    navegador.get(url)
                    time.sleep(self.config.espera_carregamento)
                    
                    self._rolar_pagina(navegador)
                    
                    dados_pagina = self._extrair_dados_html(navegador.page_source)
                    if dados_pagina:
                        todos_dados.extend(dados_pagina)
                        
                except Exception as e:
                    self.logger.error(f"Erro na página {pagina + 1}: {str(e)}")
                    continue
                
                time.sleep(random.uniform(2, 4))

            return pd.DataFrame(todos_dados) if todos_dados else None

        except Exception as e:
            self.logger.error(f"Erro crítico: {str(e)}")
            st.error(f"Erro durante a coleta: {str(e)}")
            return None

        finally:
            if navegador:
                try:
                    navegador.quit()
                except Exception as e:
                    self.logger.error(f"Erro ao fechar navegador: {str(e)}")

def check_login():
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False

def login_page():
    st.markdown("""
        <div class="login-container">
            <h1 class="login-title">🏗️ CMB Capital</h1>
            <p style='text-align: center; color: #666;'>Sistema de Coleta de Dados</p>
        </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        email = st.text_input("Email", key="email")
        password = st.text_input("Senha", type="password", key="password")
        submit = st.form_submit_button("Entrar")

        if submit:
            db = SupabaseManager()
            if db.verificar_credenciais(email, password):
                st.session_state.logged_in = True
                st.session_state.user_email = email
                st.rerun()
            else:
                st.error("Email ou senha incorretos!")

def main():
    try:
        check_login()

        if not st.session_state.logged_in:
            login_page()
            return

        if 'df' not in st.session_state:
            st.session_state.df = None
        if 'dados_salvos' not in st.session_state:
            st.session_state.dados_salvos = False
            
        col1, col2 = st.columns([6, 1])
        with col2:
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.rerun()
            
        st.title("🏗️ Coleta Informações Gerais Terrenos - Eusebio, CE")
        
        st.markdown("""
        <div style='text-align: center; padding: 1rem 0;'>
            <p style='font-size: 1.2em; color: #666;'>
                Coleta de dados de terrenos à venda em Eusébio, Ceará - ImovelWeb
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        st.info("""
        ℹ️ **Informações sobre a coleta:**
        - Serão coletadas até 9 páginas de resultados
        - Apenas terrenos em Eusébio/CE
        - Após a coleta, você pode escolher se deseja salvar os dados no banco
        """)
        
        st.markdown("<hr>", unsafe_allow_html=True)
        
        num_paginas = st.slider(
            'Selecione o número de páginas para análise',
            min_value=1,
            max_value=9,
            value=1,
            help='Quanto mais páginas, mais dados serão coletados'
        )
        
        if st.button("🚀 Iniciar Coleta", type="primary", use_container_width=True):
            st.session_state.dados_salvos = False
            with st.spinner("Iniciando coleta de dados..."):
                config = ConfiguracaoScraper()
                scraper = ScraperImovelWeb(config)
                
                st.session_state.df = scraper.coletar_dados(num_paginas)
                
        if st.session_state.df is not None and not st.session_state.df.empty:
            df = st.session_state.df
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total de Imóveis", len(df))
            with col2:
                preco_medio = df['preco_real'].mean()
                st.metric("Preço Médio", f"R$ {preco_medio:,.2f}")
            with col3:
                area_media = df['area_m2'].mean()
                st.metric("Área Média", f"{area_media:,.2f} m²")
            
            st.success("✅ Dados coletados com sucesso!")
            
            st.markdown("### 📊 Dados Coletados")
            st.dataframe(
                df.style.format({
                    'preco_real': 'R$ {:,.2f}',
                    'area_m2': '{:,.2f} m²'
                }),
                use_container_width=True
            )
            
            if not st.session_state.dados_salvos:
                st.markdown("### 💾 Salvar no Banco de Dados")
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("✅ Sim, salvar dados", key='save_button', use_container_width=True):
                        try:
                            with st.spinner("💾 Salvando dados no banco..."):
                                db = SupabaseManager()
                                registros_inseridos = db.inserir_dados(df)
                                if registros_inseridos > 0:
                                    st.session_state.dados_salvos = True
                                    st.success(f"✅ {registros_inseridos} registros salvos no banco de dados!")
                                    st.balloons()
                                else:
                                    st.warning("Nenhum registro foi salvo no banco de dados.")
                        except Exception as e:
                            st.error(f"❌ Erro ao salvar no banco de dados: {str(e)}")
                
                with col2:
                    if st.button("❌ Não salvar", key='dont_save_button', use_container_width=True):
                        st.session_state.dados_salvos = True
                        st.info("📝 Dados não foram salvos no banco.")
            
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Baixar dados em CSV",
                data=csv,
                file_name=f'terrenos_eusebio_imovelweb_{datetime.now().strftime("%Y%m%d")}.csv',
                mime='text/csv',
            )
            
            if st.session_state.dados_salvos:
                st.info("🔄 Para iniciar uma nova coleta, atualize a página.")
                
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("""
            <div style='text-align: center; padding: 1rem 0; color: #666;'>
                <p>Desenvolvido com ❤️ por Rhuan Mateus - CMB Capital</p>
                <p style='font-size: 0.8em;'>Última atualização: Janeiro 2025</p>
            </div>
        """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"❌ Erro inesperado: {str(e)}")
        st.error("Por favor, atualize a página e tente novamente.")

if __name__ == "__main__":
    main()
