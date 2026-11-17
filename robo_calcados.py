# Robô de promoções - Calçados esportivos
# Varre lojas de sneakers e manda no Telegram só o que tiver
# desconto mínimo e o tamanho certo disponível (masc 41 / fem 38 / unissex 41).

import requests, time, json, os, sys, socket
import urllib3.util.connection as _uc
_uc.allowed_gai_family = lambda: socket.AF_INET   # força IPv4 (evita travas de IPv6)

# ===== CONFIGURAÇÃO =====
PASTA = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
if not TOKEN:
    with open(os.path.join(PASTA, "token.txt"), encoding="utf-8") as _f:
        TOKEN = _f.read().strip()
CHAT_ID = "-1004445005146"
TOPICO_CALCADOS = 7
TOPICO_TECNOLOGIA = 3          # usado na próxima etapa
DESCONTO_MIN = 50              # percentual mínimo
INTERVALO = 600                # segundos entre varreduras (10 min)
MAX_POR_RODADA = 20            # evita inundar o grupo na primeira vez
ARQ_VISTOS = os.path.join(PASTA, "vistos.json")

TAM_MASC = "41"
TAM_FEM = "38"

MARCAS = ["nike", "adidas", "puma", "new balance", "on running", "olympikus",
          "asics", "mizuno", "vans", "jordan", "fila", "reebok", "converse"]

LOJAS_VTEX = {
    "Artwalk": "https://www.artwalk.com.br",
    "Authentic Feet": "https://www.authenticfeet.com.br",
    "Maze": "https://www.maze.com.br",
    "Guadalupe": "https://www.guadalupestore.com.br",
}
LOJAS_SHOPIFY = {
    "Cartel": "https://www.cartel011.com.br",
    "Kings": "https://www.kingssneakers.com.br",
}

HEADERS = {"User-Agent": "Mozilla/5.0"}
enviados_na_rodada = 0


# ===== FUNÇÕES DE APOIO =====
def carregar_vistos():
    if os.path.exists(ARQ_VISTOS):
        with open(ARQ_VISTOS) as f:
            return set(json.load(f))
    return set()

def salvar_vistos(v):
    with open(ARQ_VISTOS, "w") as f:
        json.dump(list(v), f)

def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def genero(texto):
    t = texto.lower()
    if "unissex" in t or "unisex" in t:
        return "Unissex"
    if "femin" in t or "women" in t or "wmns" in t:
        return "Feminino"
    if "mascul" in t or " men" in t:
        return "Masculino"
    return "Unissex"   # sem informação: trata como unissex (busca o 41)

def tamanho_alvo(g):
    return TAM_FEM if g == "Feminino" else TAM_MASC

def desconto(de, por):
    return (1 - por / de) * 100 if de and por and de > por else 0

def tg_post(dados, metodo="sendMessage"):
    for tentativa in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{metodo}",
                              data=dados, timeout=(10, 60))
            if not r.ok:
                print("Erro no Telegram:", r.text)
            return r.ok
        except requests.RequestException as e:
            print(f"Telegram sem resposta (tentativa {tentativa + 1}/3): {type(e).__name__}")
            time.sleep(5)
    return False

def enviar(loja, nome, g, tam, de, por, link, foto=None):
    global enviados_na_rodada
    if enviados_na_rodada >= MAX_POR_RODADA:
        return False
    texto = (f"🔥 {round(desconto(de, por))}% OFF — {loja}\n"
             f"{nome}\n"
             f"{g} · tamanho {tam} disponível\n"
             f"De {brl(de)} por {brl(por)}\n"
             f"🛒 Comprar (já vai pro carrinho): {link}")
    base = {"chat_id": CHAT_ID, "message_thread_id": TOPICO_CALCADOS}
    ok = False
    if foto:   # tenta mandar com foto; se a loja bloquear a imagem, manda só o texto
        ok = tg_post({**base, "photo": foto, "caption": texto}, "sendPhoto")
    if not ok:
        ok = tg_post({**base, "text": texto, "disable_web_page_preview": "true"})
    if not ok:
        return False
    enviados_na_rodada += 1
    time.sleep(1.5)    # respeita o limite do Telegram
    return True


# ===== LOJAS VTEX (Artwalk, Authentic Feet, Maze, Guadalupe) =====
def tamanho_do_sku(item):
    for campo in ("Tamanho", "TAMANHO", "tamanho", "Numeração"):
        if item.get(campo):
            return str(item[campo][0]).strip()
    return item.get("name", "").split()[-1] if item.get("name") else ""

def varrer_vtex(loja, base, vistos):
    achados = 0
    for marca in MARCAS:
        url = f"{base}/api/catalog_system/pub/products/search?ft={marca}&_from=0&_to=49"
        try:
            produtos = requests.get(url, headers=HEADERS, timeout=20).json()
        except Exception:
            continue
        if not isinstance(produtos, list):
            continue
        for p in produtos:
            txt = " ".join([p.get("productName", "")] + p.get("categories", [])
                           + [str(p.get("Gênero", "")), str(p.get("Genero", ""))])
            g = genero(txt)
            alvo = tamanho_alvo(g)
            for item in p.get("items", []):
                if tamanho_do_sku(item) != alvo:
                    continue
                try:
                    seller = item["sellers"][0]
                    oferta = seller["commertialOffer"]
                except (KeyError, IndexError):
                    continue
                de, por = oferta.get("ListPrice", 0), oferta.get("Price", 0)
                if oferta.get("AvailableQuantity", 0) <= 0 or desconto(de, por) < DESCONTO_MIN:
                    continue
                chave = f"{loja}-{item['itemId']}-{por}"
                if chave in vistos:
                    continue
                link = (f"{base}/checkout/cart/add?sku={item['itemId']}&qty=1"
                        f"&seller={seller.get('sellerId', '1')}&redirect=true&sc=1")
                imgs = item.get("images") or []
                foto = imgs[0].get("imageUrl") if imgs else None
                if enviar(loja, p["productName"], g, alvo, de, por, link, foto):
                    vistos.add(chave)
                    achados += 1
    return achados


# ===== LOJAS SHOPIFY (Cartel, Kings) =====
def varrer_shopify(loja, base, vistos):
    achados = 0
    for pagina in range(1, 6):
        url = f"{base}/products.json?limit=250&page={pagina}"
        try:
            produtos = requests.get(url, headers=HEADERS, timeout=20).json()["products"]
        except Exception:
            break
        if not produtos:
            break
        for p in produtos:
            tags = p.get("tags", [])
            tags = " ".join(tags) if isinstance(tags, list) else str(tags)
            txt = " ".join([p.get("title", ""), p.get("vendor", ""), p.get("product_type", ""), tags])
            if not any(m in txt.lower() for m in MARCAS):
                continue
            g = genero(txt)
            alvo = tamanho_alvo(g)
            for v in p.get("variants", []):
                opcoes = [str(v.get(k) or "").strip() for k in ("option1", "option2", "option3")]
                if alvo not in opcoes or not v.get("available"):
                    continue
                if not v.get("compare_at_price"):
                    continue
                de, por = float(v["compare_at_price"]), float(v["price"])
                if desconto(de, por) < DESCONTO_MIN:
                    continue
                chave = f"{loja}-{v['id']}-{por}"
                if chave in vistos:
                    continue
                link = f"{base}/cart/{v['id']}:1"
                foto = (v.get("featured_image") or {}).get("src") or \
                       ((p.get("images") or [{}])[0].get("src"))
                if enviar(loja, p["title"], g, alvo, de, por, link, foto):
                    vistos.add(chave)
                    achados += 1
    return achados


# ===== EXECUÇÃO =====
def rodada(vistos):
    global enviados_na_rodada
    enviados_na_rodada = 0
    for loja, base in LOJAS_VTEX.items():
        print(f"{loja}: {varrer_vtex(loja, base, vistos)} ofertas enviadas")
    for loja, base in LOJAS_SHOPIFY.items():
        print(f"{loja}: {varrer_shopify(loja, base, vistos)} ofertas enviadas")
    salvar_vistos(vistos)

if __name__ == "__main__":
    vistos = carregar_vistos()
    if "--uma" in sys.argv:          # usado na nuvem: uma rodada e termina
        rodada(vistos)
    elif "--teste" in sys.argv:
        print("Testando conexão com o Telegram...")
        ok = tg_post({"chat_id": CHAT_ID, "message_thread_id": TOPICO_CALCADOS,
                      "text": "✅ Robô conectado! Iniciando varredura de teste..."})
        print("Telegram:", "OK" if ok else "FALHOU")
        print("Rodando uma varredura de teste...")
        rodada(vistos)
        print("Teste concluído.")
    else:
        while True:
            rodada(vistos)
            print(f"Aguardando {INTERVALO // 60} minutos...")
            time.sleep(INTERVALO)
