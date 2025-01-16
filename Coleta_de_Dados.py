import streamlit as st
import pandas as pd
import time
import random
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import traceback
from supabase import create_client, Client
from dataclasses import dataclass
from typing import Optional, List, Dict
import logging
from datetime import datetime

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
    layout="wide",
    initial_sidebar_state="collapsed"
)

class SupabaseManager:
    def __init__(self):
        self.url = st.secrets["SUPABASE_URL"]
        self.key = st.secrets["SUPABASE_KEY"]
        self.supabase = create_client(self.url, self.key)

    def inserir_dados(self, df):
        result = self.supabase.table('imoveisweb').select('cardID').order('cardID.desc').limit(1).execute()
        ultimo_id = result.data[0]['cardID'] if result.data else 0
        
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

    def coletar_dados(self, num_paginas: int = 1) -> Optional[pd.DataFrame]:
        dados_total = []
        status = st.empty()
        progress_bar = st.progress(0)
        
        try:
            with sync_playwright() as p:
                # Configurações do navegador
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--no-first-run',
                        '--no-zygote',
                        '--disable-gpu'
                    ]
                )
                
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                
                page = context.new_page()
                
                for pagina in range(num_paginas):
                    status.text(f"⏳ Processando página {pagina + 1}/{num_paginas}")
                    progress_bar.progress((pagina + 1) / num_paginas)
                    
                    url = f"https://www.imovelweb.com.br/terrenos-venda-eusebio-ce{'-pagina-' + str(pagina + 1) if pagina > 0 else ''}.html"
                    
                    try:
                        page.goto(url, wait_until='networkidle', timeout=60000)
                        page.wait_for_selector('div[data-qa="posting PROPERTY"]', timeout=30000)
                        
                        # Scroll suave
                        for _ in range(10):
                            page.mouse.wheel(0, 300)
                            time.sleep(0.3)
                        
                        content = page.content()
                        dados_pagina = self._extrair_dados_html(content)
                        if dados_pagina:
                            dados_total.extend(dados_pagina)
                            
                    except Exception as e:
                        self.logger.error(f"Erro na página {pagina + 1}: {str(e)}")
                        continue
                    
                    time.sleep(random.uniform(3, 6))
                
                browser.close()
            
            if dados_total:
                return pd.DataFrame(dados_total)
            return None
            
        except Exception as e:
            self.logger.error(f"Erro crítico: {str(e)}")
            st.error(f"Erro durante a coleta: {str(e)}")
            return None

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
                
                # Converter valores numéricos
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
                except Exception as e:
                    st.error(f'Erro ao salvar no Supabase: {str(e)}')

if __name__ == "__main__":
    main()
