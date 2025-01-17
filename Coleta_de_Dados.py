import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time
import random
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from supabase import create_client
from bs4 import BeautifulSoup
import re

# Configuração da página Streamlit
st.set_page_config(
    page_title="CMB - Capital",
    page_icon="🏗️",
    layout="wide"
)

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
            
            service = Service("/usr/bin/chromedriver")
            navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
            
            return navegador
        except Exception as e:
            self.logger.error(f"Erro ao configurar navegador: {str(e)}")
            return None

    def _extrair_dados_imovel(self, html):
        """Extrai dados usando BeautifulSoup"""
        soup = BeautifulSoup(html, 'html.parser')
        
        try:
            # Identificadores de elementos baseados no teste2.py
            container = soup.find('div', {'data-qa': 'posting PROPERTY'})
            
            # Extração de dados com fallbacks
            card_id = container.get('data-id', 'Não identificado')
            
            # Preço
            preco_elem = container.find('div', {'data-qa': 'POSTING_CARD_PRICE'})
            preco = preco_elem.text.strip() if preco_elem else "0"
            preco = self._converter_preco(preco)
            
            # Endereço
            endereco_elem = container.find('div', class_='postingLocations-module__location-address__k8Ip7')
            endereco = endereco_elem.text.strip() if endereco_elem else "Endereço não disponível"
            
            # Localidade
            localidade_elem = container.find('h2', {'data-qa': 'POSTING_CARD_LOCATION'})
            localidade = localidade_elem.text.strip() if localidade_elem else "Localidade não disponível"
            
            # Área
            area_elem = container.find('span', class_='postingMainFeatures-module__posting-main-features-span__ror2o')
            area = area_elem.text.strip() if area_elem else "0"
            area = self._converter_area(area)
            
            # Link
            link_elem = container.find('a', {'data-to-posting': True})
            link = f"https://www.imovelweb.com.br{link_elem.get('data-to-posting')}" if link_elem else ""
            
            return {
                'cardID': card_id,
                'endereco': endereco,
                'localidade': localidade,
                'area_m2': area,
                'preco_real': preco,
                'link': link
            }
        
        except Exception as e:
            self.logger.error(f"Erro ao extrair dados: {str(e)}")
            return None
    
    def _converter_preco(self, valor):
        """Converte string de preço para float"""
        try:
            if isinstance(valor, str):
                # Remove 'R$ ' e converte para float
                valor_limpo = valor.replace('R$ ', '').replace('.', '').replace(',', '.')
                return float(valor_limpo)
            return float(valor)
        except:
            return 0.0
    
    def _converter_area(self, valor):
        """Extrai o número da string de área e converte para float"""
        try:
            if isinstance(valor, str):
                match = re.search(r'(\d+)', valor)
                if match:
                    return float(match.group(1))
            return float(valor)
        except:
            return 0.0

    def _encontrar_botao_proxima(self, navegador: webdriver.Chrome) -> Optional[webdriver.remote.webelement.WebElement]:
        try:
            return navegador.find_element(By.CSS_SELECTOR, 'a[title="Próxima"]')
        except:
            return None

    def coletar_dados(self, num_paginas: int = 9) -> Optional[pd.DataFrame]:
        navegador = None
        todos_dados: List[Dict] = []
        progresso = st.progress(0)
        status = st.empty()
    
        try:
            self.logger.info("Iniciando coleta de dados...")
            navegador = self._configurar_navegador()
            if navegador is None:
                st.error("Não foi possível inicializar o navegador")
                return None
    
            navegador.get(self.config.url_base)
            self.logger.info("Navegador acessou a URL com sucesso")
            
            for pagina in range(1, num_paginas + 1):
                try:
                    status.text(f"⏳ Processando página {pagina}/{num_paginas}")
                    progresso.progress(pagina / num_paginas)
                    self.logger.info(f"Processando página {pagina}")
                    
                    time.sleep(random.uniform(2, 4))
    
                    # Rolar a página para carregar elementos
                    for i in range(10):
                        navegador.execute_script(f"window.scrollTo(0, {i * 300});")
                        time.sleep(0.3)
    
                    # Encontrar todos os cards de imóveis
                    imoveis = navegador.find_elements(By.CSS_SELECTOR, 'div[data-qa="posting PROPERTY"]')
                    
                    if not imoveis:
                        self.logger.warning(f"Sem imóveis na página {pagina}")
                        break
    
                    # Extrair dados de cada imóvel
                    for imovel in imoveis:
                        html = imovel.get_attribute('outerHTML')
                        if dados := self._extrair_dados_imovel(html):
                            todos_dados.append(dados)
    
                    # Navegar para próxima página
                    if pagina < num_paginas:
                        botao_proxima = self._encontrar_botao_proxima(navegador)
                        if not botao_proxima:
                            break
                        navegador.execute_script("arguments[0].click();", botao_proxima)
                        time.sleep(2)
    
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
                try:
                    navegador.quit()
                except Exception as e:
                    self.logger.error(f"Erro ao fechar navegador: {str(e)}")

def main():
    try:
        # Títulos e descrição
        st.title("🏗️ Coleta Informações Gerais Terrenos - Eusébio, CE")
        
        st.markdown("""
        <div style='text-align: center; padding: 1rem 0;'>
            <p style='font-size: 1.2em; color: #666;'>
                Coleta de dados de terrenos à venda em Eusébio, Ceará
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Informações sobre a coleta
        st.info("""
        ℹ️ **Informações sobre a coleta:**
        - Digite o número de páginas que deseja coletar (máximo 9)
        - Apenas terrenos em Eusébio/CE
        - Após a coleta, você pode escolher se deseja salvar os dados no banco
        """)

        # Input para número de páginas
        num_paginas = st.number_input("Número de páginas para coletar", min_value=1, max_value=9, value=5)
        
        # Separador visual
        st.markdown("<hr>", unsafe_allow_html=True)
        
        # Botão centralizado
        if st.button("🚀 Iniciar Coleta", type="primary", use_container_width=True):
            st.session_state.dados_salvos = False
            with st.spinner("Iniciando coleta de dados..."):
                config = ConfiguracaoScraper()
                scraper = ScraperImovelWeb(config)
                st.session_state.df = scraper.coletar_dados(num_paginas)
                
        # Se temos dados coletados
        if hasattr(st.session_state, 'df') and st.session_state.df is not None and not st.session_state.df.empty:
            df = st.session_state.df
            
            # Métricas principais
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
            
            # Exibição dos dados
            st.markdown("### 📊 Dados Coletados")
            st.dataframe(
                df.style.format({
                    'preco_real': 'R$ {:,.2f}',
                    'area_m2': '{:,.2f} m²'
                }),
                use_container_width=True
            )
            
            # Confirmação para salvar no banco
            if not hasattr(st.session_state, 'dados_salvos') or not st.session_state.dados_salvos:
                st.markdown("### 💾 Salvar no Banco de Dados")
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("✅ Sim, salvar dados", key='save_button', use_container_width=True):
                        try:
                            with st.spinner("💾 Salvando dados no banco..."):
                                db = SupabaseManager()
                                db.inserir_dados(df)
                                st.session_state.dados_salvos = True
                                st.success("✅ Dados salvos no banco de dados!")
                                st.balloons()
                        except Exception as e:
                            st.error(f"❌ Erro ao salvar no banco de dados: {str(e)}")
                
                with col2:
                    if st.button("❌ Não salvar", key='dont_save_button', use_container_width=True):
                        st.session_state.dados_salvos = True
                        st.info("📝 Dados não foram salvos no banco.")
            
            # Botão de download
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 Baixar dados em CSV",
                data=csv,
                file_name=f'terrenos_eusebio_{datetime.now().strftime("%Y%m%d")}.csv',
                mime='text/csv',
            )
            
            if hasattr(st.session_state, 'dados_salvos') and st.session_state.dados_salvos:
                st.info("🔄 Para iniciar uma nova coleta, atualize a página.")
                
        # Rodapé
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
