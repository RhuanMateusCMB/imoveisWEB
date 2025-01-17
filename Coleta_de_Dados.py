import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from datetime import datetime
import time
import random
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from supabase import create_client

# Configuração da página Streamlit
st.set_page_config(
    page_title="CMB - Capital",
    page_icon="🏟️",
    layout="wide"
)

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 8
    pausa_rolagem: int = 2
    espera_carregamento: int = 4
    url_base: str = "https://www.imovelweb.com.br/terrenos-venda-eusebio-ce.html"

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def limpar_tabela(self):
        self.supabase.table('imoveisweb').delete().neq('id', 0).execute()

    def inserir_dados(self, df):
        registros = df.to_dict('records')
        self.supabase.table('imoveisweb').insert(registros).execute()

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

    def _configurar_navegador(self) -> webdriver.Chrome:
        try:
            opcoes_chrome = Options()
            opcoes_chrome.add_argument('--headless=new')
            opcoes_chrome.add_argument('--no-sandbox')
            opcoes_chrome.add_argument('--disable-dev-shm-usage')
            opcoes_chrome.add_argument('--window-size=1920,1080')
            opcoes_chrome.add_argument('--disable-blink-features=AutomationControlled')

            service = Service("/usr/bin/chromedriver")  # Substitua pelo caminho correto
            navegador = webdriver.Chrome(service=service, options=opcoes_chrome)

            return navegador
        except Exception as e:
            self.logger.error(f"Erro ao configurar navegador: {str(e)}")
            return None

    def _extrair_dados_imovel(self, imovel: webdriver.remote.webelement.WebElement) -> Optional[Dict]:
        try:
            card_id = imovel.get_attribute('data-id')
            preco = imovel.find_element(By.CSS_SELECTOR, 'div.postingPrices-module__price__fqpP5').text
            area = imovel.find_element(By.CSS_SELECTOR, 'span.postingMainFeatures-module__posting-main-features-span__ror2o').text
            endereco = imovel.find_element(By.CSS_SELECTOR, 'div.postingLocations-module__location-address__k8Ip7').text
            link = imovel.find_element(By.CSS_SELECTOR, 'a[href*="/propriedades/"]').get_attribute('href')
            return {'cardID': card_id, 'preco': preco, 'area': area, 'endereco': endereco, 'link': link}
        except Exception as e:
            self.logger.error(f"Erro ao extrair dados: {str(e)}")
            return None

    def coletar_dados(self, num_paginas: int) -> Optional[pd.DataFrame]:
        navegador = self._configurar_navegador()
        if navegador is None:
            st.error("Erro ao iniciar o navegador")
            return None

        todos_dados = []
        try:
            navegador.get(self.config.url_base)
            for pagina in range(num_paginas):
                imoveis = navegador.find_elements(By.CSS_SELECTOR, 'div[data-qa="POSTING PROPERTY"]')
                for imovel in imoveis:
                    dados = self._extrair_dados_imovel(imovel)
                    if dados:
                        todos_dados.append(dados)
                botao_proxima = navegador.find_elements(By.CSS_SELECTOR, 'a[title="Próxima"]')
                if not botao_proxima:
                    break
                navegador.execute_script("arguments[0].click();", botao_proxima[0])
                time.sleep(self.config.tempo_espera)

            return pd.DataFrame(todos_dados) if todos_dados else None
        finally:
            navegador.quit()

# Main
if __name__ == "__main__":
    st.title("🏟️ Coleta de Dados - Terrenos em Eusébio")

    num_paginas = st.number_input("Número de páginas a coletar", min_value=1, max_value=10, value=5)

    if st.button("Iniciar Coleta"):
        config = ConfiguracaoScraper()
        scraper = ScraperImovelWeb(config)
        with st.spinner("Coletando dados..."):
            dados = scraper.coletar_dados(num_paginas)
        if dados is not None:
            st.success("Coleta realizada com sucesso!")
            st.dataframe(dados)
        else:
            st.error("Nenhum dado coletado ou ocorreu um erro.")
