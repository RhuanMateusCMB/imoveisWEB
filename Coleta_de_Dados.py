# Bibliotecas para interface web
import streamlit as st
import streamlit.components.v1 as components

# Gmail API
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText

# Manipulação de dados
import pandas as pd

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Utilitários
import time
import random
from datetime import datetime
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from supabase import create_client

# Configuração da página Streamlit
st.set_page_config(
    page_title="CMB - Capital",
    page_icon="🏗️",
    layout="wide"
)

# Estilo CSS personalizado
st.markdown("""
    <style>
    /* Estilo original do botão */
    .stButton>button {
        width: 100%;
        height: 3em;
        font-size: 20px;
        background-color: #FF4B4B !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
        border-radius: 5px !important;
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        background-color: #FF3333 !important;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2) !important;
    }
    /* Estilo para botão desabilitado */
    .stButton>button:disabled {
        background-color: #4f4f4f !important;
        cursor: not-allowed !important;
        opacity: 0.6 !important;
    }
    </style>
    """, unsafe_allow_html=True)

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 8
    pausa_rolagem: int = 2
    espera_carregamento: int = 4
    url_base: str = "https://www.imovelweb.com.br/terrenos-venda-eusebio-ce.html"
    tentativas_max: int = 3

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def inserir_dados(self, df):
        result = self.supabase.table('imoveisweb').select('id').order('id.desc').limit(1).execute()
        ultimo_id = result.data[0]['id'] if result.data else 0
        
        df['id'] = df['id'].apply(lambda x: x + ultimo_id)
        df['data_coleta'] = pd.to_datetime(df['data_coleta']).dt.strftime('%Y-%m-%d')
        
        registros = df.to_dict('records')
        self.supabase.table('imoveisweb').insert(registros).execute()

    def verificar_coleta_hoje(self):
        try:
            hoje = datetime.now().strftime('%Y-%m-%d')
            result = self.supabase.table('imoveisweb').select('data_coleta').eq('data_coleta', hoje).execute()
            return len(result.data) > 0
        except Exception as e:
            st.error(f"Erro ao verificar coleta: {str(e)}")
            return True

    def buscar_historico(self):
        try:
            result = self.supabase.rpc(
                'get_coleta_historico',
                {}).execute()
            return result.data
        except Exception as e:
            st.error(f"Erro ao buscar histórico: {str(e)}")
            return []

class GmailSender:
   def __init__(self):
       self.creds = Credentials.from_authorized_user_info(
           info={
               "client_id": st.secrets["GOOGLE_CREDENTIALS"]["client_id"],
               "client_secret": st.secrets["GOOGLE_CREDENTIALS"]["client_secret"],
               "refresh_token": st.secrets["GOOGLE_CREDENTIALS"]["refresh_token"]
           },
           scopes=['https://www.googleapis.com/auth/gmail.send']
       )
       self.service = build('gmail', 'v1', credentials=self.creds)

   def enviar_email(self, total_registros):
       message = MIMEText(f"Coleta de lotes do site ImovelWeb foi concluída com sucesso. Total de dados coletados: {total_registros}")
       message['to'] = 'rhuanmateuscmb@gmail.com'
       message['subject'] = 'Coleta ImovelWeb Concluída'
       message['from'] = st.secrets["GOOGLE_CREDENTIALS"]["client_email"]
       
       raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
       
       try:
           self.service.users().messages().send(
               userId='me', body={'raw': raw}).execute()
           return True
       except Exception as e:
           st.error(f"Erro ao enviar email: {str(e)}")
           return False

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
            
            user_agent = self._get_random_user_agent()
            opcoes_chrome.add_argument(f'--user-agent={user_agent}')
            
            service = Service("/usr/bin/chromedriver")
            navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
            
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
        except Exception as e:
            self.logger.error(f"Erro ao rolar página: {str(e)}")

    def _extrair_dados_imovel(self, imovel, id_global: int, pagina: int) -> Optional[Dict]:
        try:
            wait = WebDriverWait(imovel, 10)
            
            # Extrair cardID 
            try:
                card_id = imovel.get_attribute('data-id')
            except:
                card_id = f"CARD_{id_global}"

            # Extrair preço
            try:
                preco_elemento = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.postingPrices-module__price__fqpP5'))
                )
                preco_texto = preco_elemento.text
                preco = float(preco_texto.replace('R$', '').replace('.', '').replace(',', '.').strip())
            except Exception as e:
                self.logger.warning(f"Erro ao extrair preço: {e}")
                return None

            # Extrair área
            try:
                area_elemento = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.postingMainFeatures-module__posting-main-features-listing__BFHHQ'))
                )
                area_texto = area_elemento.text
                area = float(area_texto.replace('m² tot.', '').replace(',', '.').strip())
            except Exception as e:
                self.logger.warning(f"Erro ao extrair área: {e}")
                return None

            # Extrair endereço e localidade
            try:
                endereco_completo = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.postingLocations-module__location-text__Y9QrY'))
                ).text
                # O texto vem no formato "Bairro, Cidade" - vamos separar
                partes = endereco_completo.split(',')
                localidade = partes[0].strip() if len(partes) > 0 else "Não informado"
                
                # Tentar pegar o endereço mais detalhado se disponível
                try:
                    endereco_detalhado = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '.postingLocations-module__location-address__k8Ip7'))
                    ).text
                    endereco = endereco_detalhado if endereco_detalhado else endereco_completo
                except:
                    endereco = endereco_completo
                    
            except Exception as e:
                self.logger.warning(f"Erro ao extrair endereço: {e}")
                endereco = "Endereço não disponível"
                localidade = "Não informado"

            # Extrair link
            try:
                desc_element = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.postingCard-module__posting-description__r17OH'))
                )
                link = desc_element.find_element(By.TAG_NAME, 'a').get_attribute('href')
            except Exception:
                link = ""

            return {
                'id': id_global,
                'cardID': card_id,
                'preco_Real': preco,
                'endereco': endereco,
                'localidade': localidade,
                'area_m2': area,
                'link': link,
                'data_coleta': datetime.now().strftime("%Y-%m-%d")
            }

        except Exception as e:
            self.logger.error(f"Erro ao extrair dados: {str(e)}")
            return None

    def coletar_dados(self, num_paginas: int = 9) -> Optional[pd.DataFrame]:
        navegador = None
        todos_dados = []
        id_global = 0
        progresso = st.progress(0)
        status = st.empty()

        try:
            navegador = self._configurar_navegador()
            if navegador is None:
                return None

            for pagina in range(1, num_paginas + 1):
                try:
                    # Navegação entre páginas usando a estrutura de URL do ImovelWeb
                    if pagina == 1:
                        navegador.get(self.config.url_base)
                    else:
                        url_pagina = f"/terrenos-venda-eusebio-ce-pagina-{pagina}.html"
                        navegador.get(f"https://www.imovelweb.com.br{url_pagina}")
                    
                    status.text(f"⏳ Processando página {pagina}/{num_paginas}")
                    progresso.progress(pagina / num_paginas)

                    time.sleep(self.config.espera_carregamento)
                    self._rolar_pagina(navegador)

                    # Coleta dos imóveis da página atual
                    imoveis = WebDriverWait(navegador, self.config.tempo_espera).until(
                        EC.presence_of_all_elements_located(
                            (By.CSS_SELECTOR, '.postingCardLayout-module__posting-card-layout__Lklt9')
                        )
                    )

                    for imovel in imoveis:
                        id_global += 1
                        if dados := self._extrair_dados_imovel(imovel, id_global, pagina):
                            todos_dados.append(dados)

                    time.sleep(random.uniform(2, 4))

                except Exception as e:
                    self.logger.error(f"Erro na página {pagina}: {str(e)}")
                    continue

            return pd.DataFrame(todos_dados) if todos_dados else None

        except Exception as e:
            self.logger.error(f"Erro crítico: {str(e)}")
            st.error(f"Erro durante a coleta: {str(e)}")
            return None

        finally:
            if navegador:
                navegador.quit()

def main():
    try:
        # Título e descrição
        st.title("🏗️ Coleta Informações Gerais Terrenos - Eusebio, CE")
        
        with st.container():
            st.markdown("""
                <p style='text-align: center; color: #666; margin-bottom: 2rem;'>
                    Coleta de dados de terrenos à venda em Eusébio, Ceará
                </p>
            """, unsafe_allow_html=True)
            
            # Container de informações
            with st.expander("ℹ️ Informações sobre a coleta", expanded=True):
                st.markdown("""
                - Serão coletadas 9 páginas de resultados
                - Apenas terrenos em Eusébio/CE
                """)
        
        # Container principal
        db = SupabaseManager()
        coleta_realizada = db.verificar_coleta_hoje()

        # Aviso de coleta já realizada
        if coleta_realizada:
            st.warning("Coleta já realizada hoje. Nova coleta disponível amanhã.", icon="⚠️")

        # Botões lado a lado
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🚀 Iniciar Coleta", disabled=coleta_realizada, use_container_width=True):
                with st.spinner("Iniciando coleta de dados..."):
                    config = ConfiguracaoScraper()
                    scraper = ScraperImovelWeb(config)
                    df = scraper.coletar_dados()
                    
                    if df is not None:
                        try:
                            db.inserir_dados(df)
                            gmail = GmailSender()
                            gmail.enviar_email(len(df))
                            st.success("✅ Dados coletados e salvos com sucesso!")
                            st.balloons()
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao salvar no banco: {str(e)}")

        with col2:
            if st.button("📊 Ver Histórico", type="secondary", use_container_width=True):
                historico = db.buscar_historico()
                if historico:
                    st.markdown("### 📅 Histórico de Coletas")
                    for registro in historico:
                        st.info(f"{registro['data_coleta']}: {registro['total']} registros")
                else:
                    st.info("Nenhuma coleta registrada")
                    
    except Exception as e:
        st.error(f"❌ Erro inesperado: {str(e)}")

if __name__ == "__main__":
    main()
