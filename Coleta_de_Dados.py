import streamlit as st
import pandas as pd
import time
import random
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import traceback
from supabase import create_client, Client
from dataclasses import dataclass
import logging
from datetime import datetime
from typing import Optional, List, Dict

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 8
    pausa_rolagem: int = 2
    espera_carregamento: int = 4
    tentativas_max: int = 3

# Configuração do tema e estilo da página
st.set_page_config(
    page_title="Coletor de Dados Imobiliários - Eusébio",
    page_icon="🏠",
    layout="wide"
)

# CSS customizado
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
    </style>
""", unsafe_allow_html=True)

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def inserir_dados(self, df):
        registros_inseridos = 0
        for _, row in df.iterrows():
            try:
                dados_validados = {
                    'cardID': str(row['cardid']),
                    'preco_Real': float(row['preco_real']),
                    'endereco': str(row['endereco']),
                    'localidade': str(row['localidade']),
                    'area_m2': float(row['area_m2']),
                    'link': str(row['link'])
                }
                self.supabase.table('imoveisweb').insert([dados_validados]).execute()
                registros_inseridos += 1
            except Exception as e:
                st.error(f"Erro ao inserir registro: {str(e)}")
                continue
        return registros_inseridos

class ImoveisScraper:
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
            
            # Headers mais realistas
            user_agent = self._get_random_user_agent()
            opcoes_chrome.add_argument(f'--user-agent={user_agent}')
            opcoes_chrome.add_argument('--accept-language=pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7')
            
            # Configurações adicionais
            opcoes_chrome.add_argument('--disable-notifications')
            opcoes_chrome.add_argument('--disable-popup-blocking')
            opcoes_chrome.add_argument('--disable-extensions')
            opcoes_chrome.add_argument('--disable-gpu')
            
            service = Service("/usr/bin/chromedriver")
            navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
            
            # Configurações adicionais para evitar detecção
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
                
                preco_decimal = self._converter_preco(preco)
                area_decimal = self._converter_area(area)
                
                dados.append({
                    'cardid': card_id,
                    'preco_real': float(preco_decimal),
                    'endereco': endereco,
                    'localidade': localidade,
                    'area_m2': float(area_decimal),
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
                match = re.search(r'(\d+)', valor)
                if match:
                    return float(match.group(1))
            return float(valor)
        except:
            return 0.0

    def coletar_dados(self, num_paginas: int = 1) -> Optional[pd.DataFrame]:
        navegador = None
        dados_total = []
        status = st.empty()
        progress_bar = st.progress(0)
        
        try:
            navegador = self._configurar_navegador()
            if not navegador:
                st.error("Não foi possível inicializar o navegador")
                return None

            for pagina in range(num_paginas):
                status.text(f"⏳ Processando página {pagina + 1}/{num_paginas}")
                progress_bar.progress((pagina + 1) / num_paginas)
                
                url = f"https://www.imovelweb.com.br/terrenos-venda-eusebio-ce{'-pagina-' + str(pagina + 1) if pagina > 0 else ''}.html"
                
                try:
                    navegador.get(url)
                    time.sleep(self.config.espera_carregamento)
                    
                    self._rolar_pagina(navegador)
                    
                    espera = WebDriverWait(navegador, self.config.tempo_espera)
                    espera.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-qa="posting PROPERTY"]')))
                    
                    dados_pagina = self._extrair_dados_html(navegador.page_source)
                    if dados_pagina:
                        dados_total.extend(dados_pagina)
                        
                except Exception as e:
                    self.logger.error(f"Erro na página {pagina + 1}: {str(e)}")
                    continue
                
                time.sleep(random.uniform(3, 6))
            
            if dados_total:
                return pd.DataFrame(dados_total)
            return None
            
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

def main():
    st.title('🏠 Coletor de Dados Imobiliários - Eusébio')
    st.markdown("""
        <div style='margin-bottom: 2rem;'>
            Ferramenta automatizada para coleta de dados de terrenos à venda no Eusébio-CE.
            Os dados são atualizados em tempo real e armazenados de forma segura.
        </div>
    """, unsafe_allow_html=True)
    
    config = ConfiguracaoScraper()
    scraper = ImoveisScraper(config)
    
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
        df = scraper.coletar_dados(num_paginas)
        
        if df is not None and not df.empty:
            st.success('✅ Coleta finalizada com sucesso!')
            
            st.subheader('📊 Resumo dos Dados Coletados')
            st.dataframe(
                df,
                column_config={
                    "preco_real": st.column_config.NumberColumn("Preço (R$)", format="R$ %.2f"),
                    "area_m2": st.column_config.NumberColumn("Área (m²)", format="%.2f m²"),
                },
                hide_index=True
            )
            
            if st.button('💾 Salvar no Supabase'):
                try:
                    db = SupabaseManager()
                    registros_inseridos = db.inserir_dados(df)
                    st.success(f'✅ {registros_inseridos} registros inseridos com sucesso!')
                    st.balloons()
                except Exception as e:
                    st.error(f'Erro ao salvar no Supabase: {str(e)}')
            
            # Botão para download dos dados
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Baixar CSV",
                data=csv,
                file_name=f'terrenos_eusebio_{datetime.now().strftime("%Y%m%d")}.csv',
                mime='text/csv',
            )

if __name__ == "__main__":
    main()
