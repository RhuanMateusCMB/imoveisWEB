import streamlit as st
import cloudscraper
from fake_useragent import UserAgent
import pandas as pd
from bs4 import BeautifulSoup
import re
from datetime import datetime
import logging
import random
import time
from typing import Optional, Dict, List
from dataclasses import dataclass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ConfiguracaoScraper:
    tempo_espera: int = 15
    url_base: str = "https://www.imovelweb.com.br/terrenos-venda-eusebio-ce.html"
    tentativas_max: int = 5
    delay_min: float = 3.0
    delay_max: float = 7.0

class ScraperImovelWeb:
    def __init__(self, config: ConfiguracaoScraper):
        self.config = config
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=1,  # Delay entre requisições
            disable_warnings=True  # Desabilitar avisos
        )
        self.ua = UserAgent()

    def _gerar_headers(self) -> Dict[str, str]:
        """Gera headers realistas para requisições."""
        return {
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3',
            'Referer': 'https://www.google.com',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Accept-Encoding': 'gzip, deflate, br',
            'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"'
        }

    def _limpar_valor(self, texto: str) -> Optional[float]:
        """Limpa e converte valores monetários ou numéricos."""
        try:
            # Remove caracteres não numéricos exceto vírgula
            valor_limpo = ''.join(c for c in texto if c.isdigit() or c == ',')
            return float(valor_limpo.replace(',', '.'))
        except (ValueError, TypeError):
            return None

    def _extrair_dados_imovel(self, imovel, id_global: int, pagina: int) -> Optional[Dict]:
        """Extrai dados de um imóvel usando BeautifulSoup."""
        try:
            # Seletores múltiplos para maior robustez
            seletores_preco = [
                {'tag': 'span', 'class': re.compile(r'(price|valor)')},
                {'tag': 'div', 'class': re.compile(r'(price|valor)')}
            ]
            
            seletores_area = [
                {'tag': 'span', 'class': re.compile(r'(area|tamanho)')},
                {'tag': 'div', 'class': re.compile(r'(area|tamanho)')}
            ]
            
            seletores_endereco = [
                {'tag': 'span', 'class': re.compile(r'(address|localizacao)')},
                {'tag': 'div', 'class': re.compile(r'(address|localizacao)')}
            ]

            def encontrar_elemento(seletores):
                for selector in seletores:
                    elemento = imovel.find(selector['tag'], class_=selector['class'])
                    if elemento:
                        return elemento
                return None

            # Extrair preço
            preco_elem = encontrar_elemento(seletores_preco)
            preco = self._limpar_valor(preco_elem.text) if preco_elem else None

            # Extrair área
            area_elem = encontrar_elemento(seletores_area)
            area = self._limpar_valor(area_elem.text) if area_elem else None

            # Extrair endereço
            endereco_elem = encontrar_elemento(seletores_endereco)
            endereco = endereco_elem.text.strip() if endereco_elem else "Endereço não disponível"

            # Extrair link
            link_elem = imovel.find('a', href=True)
            link = link_elem['href'] if link_elem else ""

            return {
                'id': id_global,
                'preco_Real': preco,
                'endereco': endereco,
                'area_m2': area,
                'link': link,
                'data_coleta': datetime.now().strftime("%Y-%m-%d")
            } if preco and area else None

        except Exception as e:
            logger.error(f"Erro ao extrair dados na página {pagina}: {e}")
            return None
        
    def coletar_dados(self, num_paginas: int = 9) -> Optional[pd.DataFrame]:
        """Coleta dados de múltiplas páginas."""
        todos_dados = []
        
        for pagina in range(1, num_paginas + 1):
            tentativas = 0
            while tentativas < self.config.tentativas_max:
                try:
                    # Construir URL
                    url = (f"{self.config.url_base}pagina-{pagina}.html" 
                        if pagina > 1 else self.config.url_base)
                    
                    # Adicionar delay entre requisições
                    time.sleep(random.uniform(self.config.delay_min, self.config.delay_max))
                    
                    # Fazer requisição com headers
                    resposta = self.scraper.get(
                        url, 
                        headers=self._gerar_headers(),
                        timeout=30,
                        allow_redirects=True
                    )
                    
                    # Verificar sucesso da requisição
                    if resposta.status_code in [200, 302]:
                        # Parsear HTML
                        soup = BeautifulSoup(resposta.text, 'html.parser')
                        
                        # Encontrar elementos de imóveis com múltiplos seletores
                        seletores_imoveis = [
                            {'tag': 'div', 'class': re.compile(r'(property|card|listing)')},
                            {'tag': 'article', 'class': re.compile(r'(property|card|listing)')}
                        ]
                        
                        imoveis_encontrados = False
                        for selector in seletores_imoveis:
                            imoveis = soup.find_all(selector['tag'], class_=selector['class'])
                            
                            if imoveis:
                                imoveis_encontrados = True
                                logger.info(f"Página {pagina}: {len(imoveis)} imóveis encontrados")
                                
                                for imovel in imoveis:
                                    dados = self._extrair_dados_imovel(imovel, len(todos_dados) + 1, pagina)
                                    if dados:
                                        todos_dados.append(dados)
                                break
                        
                        if not imoveis_encontrados:
                            logger.warning(f"Nenhum imóvel encontrado na página {pagina}")
                        
                        # Sair do loop de tentativas se sucesso
                        break
                    
                    else:
                        logger.error(f"Erro ao acessar página {pagina}: {resposta.status_code}")
                        logger.error(f"Conteúdo da resposta: {resposta.text[:500]}")
                        tentativas += 1
                        time.sleep(random.uniform(2, 5))  # Delay entre tentativas
                
                except Exception as e:
                    logger.error(f"Erro na página {pagina}: {e}")
                    tentativas += 1
                    time.sleep(random.uniform(2, 5))  # Delay entre tentativas
        
        return pd.DataFrame(todos_dados) if todos_dados else None

def main():
    st.title("🏗️ Coleta de Terrenos em Eusébio, CE")
    
    config = ConfiguracaoScraper()
    scraper = ScraperImovelWeb(config)
    
    if st.button("Iniciar Coleta"):
        with st.spinner("Coletando dados..."):
            df = scraper.coletar_dados()
            
            if df is not None and not df.empty:
                st.success(f"Coleta concluída. {len(df)} registros encontrados.")
                st.dataframe(df)
                
                # Opção para salvar CSV
                csv = df.to_csv(index=False)
                st.download_button(
                    label="Baixar dados como CSV",
                    data=csv,
                    file_name='terrenos_eusebio.csv',
                    mime='text/csv'
                )
            else:
                st.warning("Nenhum dado coletado.")

if __name__ == "__main__":
    main()
