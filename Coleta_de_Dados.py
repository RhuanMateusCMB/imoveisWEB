import streamlit as st
import streamlit.components.v1 as components
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
from datetime import datetime
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from supabase import create_client
import backoff
import os

# Configuração do logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 15
    pausa_rolagem: int = 3
    espera_carregamento: int = 8
    url_base: str = "https://www.imovelweb.com.br/terrenos-venda-eusebio-ce.html"
    tentativas_max: int = 5
    delay_min: float = 2.0
    delay_max: float = 5.0

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
            return result.data or []
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
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1'
        ]

    def _get_random_user_agent(self):
        return random.choice(self.user_agents)

    def _configurar_navegador(self) -> webdriver.Chrome:
        try:
            opcoes_chrome = Options()
            opcoes_chrome.add_argument('--headless')
            opcoes_chrome.add_argument('--no-sandbox')
            opcoes_chrome.add_argument('--disable-dev-shm-usage')
            opcoes_chrome.add_argument('--disable-gpu')
            opcoes_chrome.add_argument('--disable-infobars')
            opcoes_chrome.add_argument('--window-size=1920,1080')
            opcoes_chrome.add_argument('--disable-blink-features=AutomationControlled')
            
            opcoes_chrome.add_experimental_option('excludeSwitches', ['enable-automation'])
            opcoes_chrome.add_experimental_option('useAutomationExtension', False)
            
            user_agent = self._get_random_user_agent()
            opcoes_chrome.add_argument(f'--user-agent={user_agent}')
            
            prefs = {
                "profile.default_content_setting_values.notifications": 2,
                "profile.managed_default_content_settings.images": 2
            }
            opcoes_chrome.add_experimental_option("prefs", prefs)
            
            service = Service(ChromeDriverManager().install())
            navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
            navegador.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
            return navegador
        except Exception as e:
            logger.error(f"Erro ao configurar navegador: {str(e)}")
            return None

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    def _rolar_pagina(self, navegador: webdriver.Chrome) -> None:
        try:
            altura_total = navegador.execute_script("return document.body.scrollHeight")
            altura_atual = 0
            passo = altura_total / 6  # Mais passos para rolagem mais suave
            
            for _ in range(6):
                altura_atual += passo
                navegador.execute_script(f"window.scrollTo(0, {altura_atual});")
                time.sleep(random.uniform(0.8, 1.5))
                
            # Rolar de volta ao topo aleatoriamente
            if random.random() < 0.3:
                navegador.execute_script("window.scrollTo(0, 0);")
                time.sleep(random.uniform(0.5, 1.0))
        except Exception as e:
            logger.error(f"Erro ao rolar página: {str(e)}")
            raise

    def _extrair_dados_imovel(self, imovel, id_global: int, pagina: int) -> Optional[Dict]:
        try:
            # Log do HTML do elemento completo para debugging
            try:
                html_elemento = imovel.get_attribute('outerHTML')
                logger.info(f"HTML do elemento na página {pagina}: {html_elemento[:500]}...")  # Limita para não poluir log
            except Exception as e:
                logger.warning(f"Não foi possível capturar HTML completo: {e}")

            # Lista de seletores para aumentar robustez
            seletores_preco = [
                '[data-qa="POSTING_CARD_PRICE"]',
                '.price-card',
                '.iw-card-price',
                '[class*="price"]'
            ]

            seletores_area = [
                '[data-qa="POSTING_CARD_FEATURES"]',
                '.area-card',
                '.iw-card-area',
                '[class*="area"]'
            ]

            seletores_endereco = [
                '[data-qa="POSTING_CARD_LOCATION"]', 
                '.location-card', 
                '.iw-card-location',
                '[class*="address"]'
            ]

            # Função helper para extrair dados com múltiplos seletores
            def extrair_texto_com_seletores(seletores_lista):
                for selector in seletores_lista:
                    try:
                        elemento = imovel.find_element(By.CSS_SELECTOR, selector)
                        return elemento.text
                    except:
                        continue
                return None

            # Extrair preço
            preco_texto = extrair_texto_com_seletores(seletores_preco)
            preco = float(''.join(filter(str.isdigit, preco_texto.replace(',', '.')))) if preco_texto else None

            # Extrair área
            area_texto = extrair_texto_com_seletores(seletores_area)
            area = float(''.join(filter(str.isdigit, area_texto.replace(',', '.')))) if area_texto else None

            # Extrair endereço
            endereco = extrair_texto_com_seletores(seletores_endereco) or "Endereço não disponível"

            # Tentar extrair link
            try:
                link = imovel.find_element(By.TAG_NAME, 'a').get_attribute('href')
            except:
                link = ""

            return {
                'id': id_global,
                'cardID': imovel.get_attribute('data-id'),
                'preco_Real': preco,
                'endereco': endereco,
                'area_m2': area,
                'link': link,
                'data_coleta': datetime.now().strftime("%Y-%m-%d")
            } if preco and area else None

        except Exception as e:
            logger.error(f"Erro ao extrair dados na página {pagina}: {str(e)}")
            return None

    def coletar_dados(self, num_paginas: int = 9) -> Optional[pd.DataFrame]:
        todos_dados = []
        navegador = None
        
        try:
            navegador = self._configurar_navegador()
            if navegador is None:
                return None

            for pagina in range(1, num_paginas + 1):
                try:
                    url = (f"{self.config.url_base}pagina-{pagina}.html" 
                        if pagina > 1 else self.config.url_base)
                    
                    navegador.get(url)
                    time.sleep(random.uniform(3, 5))  # Delay aleatório
                    
                    # Rola a página para carregar elementos lazy
                    self._rolar_pagina(navegador)
                    
                    # Seletores de imoveis com fallback
                    seletores_imoveis = [
                        '[data-qa="posting PROPERTY"]',
                        '.imovel-card',
                        '[class*="property-card"]'
                    ]

                    imoveis_encontrados = False
                    for selector in seletores_imoveis:
                        imoveis = navegador.find_elements(By.CSS_SELECTOR, selector)
                        if imoveis:
                            imoveis_encontrados = True
                            break

                    if not imoveis_encontrados:
                        logger.warning(f"Nenhum imóvel encontrado na página {pagina}")
                        continue

                    for imovel in imoveis:
                        dados = self._extrair_dados_imovel(imovel, len(todos_dados) + 1, pagina)
                        if dados:
                            todos_dados.append(dados)
                            
                except Exception as e:
                    logger.error(f"Erro na página {pagina}: {e}")
                    continue
                    
            return pd.DataFrame(todos_dados) if todos_dados else None

        finally:
            if navegador:
                navegador.quit()

def main():
    st.title("🏗️ Coleta Informações Gerais Terrenos - Eusebio, CE")
    
    with st.container():
        st.markdown("""
            <p style='text-align: center; color: #666; margin-bottom: 2rem;'>
                Coleta de dados de terrenos à venda em Eusébio, Ceará
            </p>
        """, unsafe_allow_html=True)
        
        with st.expander("ℹ️ Informações sobre a coleta", expanded=True):
            st.markdown("""
            - Serão coletadas 9 páginas de resultados
            - Apenas terrenos em Eusébio/CE
            """)
    
    db = SupabaseManager()
    coleta_realizada = db.verificar_coleta_hoje()

    if coleta_realizada:
        st.warning("Coleta já realizada hoje. Nova coleta disponível amanhã.", icon="⚠️")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Iniciar Coleta", disabled=coleta_realizada, use_container_width=True):
            with st.spinner("Iniciando coleta de dados..."):
                config = ConfiguracaoScraper()
                scraper = ScraperImovelWeb(config)
                df = scraper.coletar_dados()
                if df is not None and not df.empty:
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
                else:
                    st.warning("Nenhum dado foi coletado.")

    with col2:
        if st.button("📊 Ver Histórico", type="secondary", use_container_width=True):
            historico = db.buscar_historico()
            if historico:
                st.markdown("### 📅 Histórico de Coletas")
                for registro in historico:
                    st.info(f"{registro['data_coleta']}: {registro['total']} registros")
            else:
                st.info("Nenhuma coleta registrada")
                
if __name__ == "__main__":
    main()
