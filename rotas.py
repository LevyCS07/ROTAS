import streamlit as st
import pandas as pd
import openrouteservice
from lxml import etree
import folium
from streamlit_folium import st_folium
import io
import requests
import time

# === CONFIGURAÇÕES ===
ORS_API_KEY = st.secrets["ORS_API_KEY"]
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

st.title("🚗 Gerador de Rotas + Endereços")

uploaded_file = st.file_uploader("Envie sua planilha", type=["xlsx"])

# === MAPA DESTINO ===
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)
st.write("Clique no mapa para escolher o destino final")
map_data = st_folium(m, height=400, width=700)

destino_final = None
if map_data and map_data["last_clicked"]:
    destino_final = (
        map_data["last_clicked"]["lat"],
        map_data["last_clicked"]["lng"]
    )
    st.success(f"Destino selecionado: {destino_final}")

# === FUNÇÃO GOOGLE ===
@st.cache_data
def obter_endereco_google(lat: float, lon: float):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lon}", "key": GOOGLE_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data["results"]:
                comps = data["results"][0]["address_components"]
                rua = bairro = ""
                for c in comps:
                    if "route" in c["types"]:
                        rua = c["long_name"]
                    if "sublocality" in c["types"] or "neighborhood" in c["types"]:
                        bairro = c["long_name"]
                return rua, bairro
    except Exception:
        pass
    return "Não encontrado", "Não encontrado"

# === FUNÇÃO KML ===
def gerar_kml(grupo, coords, destino_final, tipo):
    kml_root = etree.Element('kml', xmlns="http://www.opengis.net/kml/2.2")
    document = etree.SubElement(kml_root, 'Document')

    for _, row in grupo.iterrows():
        placemark = etree.SubElement(document, 'Placemark')
        etree.SubElement(placemark, 'name').text = str(row['COLABORADOR'])
        point = etree.SubElement(placemark, 'Point')
        coord = etree.SubElement(point, 'coordinates')
        if tipo == "Entrada":
            coord.text = f"{row['LONG E']},{row['LAT E']},0"
        else:
            coord.text = f"{row['LONG S']},{row['LAT S']},0"

    # destino
    pm_dest = etree.SubElement(document, 'Placemark')
    etree.SubElement(pm_dest, 'name').text = "Destino Final"
    pt_dest = etree.SubElement(pm_dest, 'Point')
    etree.SubElement(pt_dest, 'coordinates').text = f"{destino_final[1]},{destino_final[0]},0"

    # linha
    linha = etree.SubElement(document, 'Placemark')
    etree.SubElement(linha, 'name').text = f"Caminho ({tipo})"
    style = etree.SubElement(linha, 'Style')
    ls = etree.SubElement(style, 'LineStyle')
    etree.SubElement(ls, 'color').text = 'ff0000ff'
    etree.SubElement(ls, 'width').text = '4'
    ls_str = etree.SubElement(linha, 'LineString')
    etree.SubElement(ls_str, 'tessellate').text = '1'
    coords_txt = " ".join([f"{c[0]},{c[1]},0" for c in coords])
    etree.SubElement(ls_str, 'coordinates').text = coords_txt

    tree = etree.ElementTree(kml_root)
    kml_bytes = io.BytesIO()
    tree.write(kml_bytes, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    kml_bytes.seek(0)  # FIX: resetar ponteiro antes de retornar
    return kml_bytes

# === VALIDAÇÃO DA PLANILHA ===
def validar_planilha(df):
    colunas_obrigatorias = ['COLABORADOR', 'ROTA', 'LAT E', 'LONG E', 'LAT S', 'LONG S']
    faltando = [c for c in colunas_obrigatorias if c not in df.columns]
    return faltando

# === PROCESSAMENTO ===
MAX_WAYPOINTS = 48  # limite seguro ORS (50 - origem - destino)

if uploaded_file and destino_final and st.button("GERAR ROTAS E RELATÓRIO"):

    # Leitura com validação
    try:
        df = pd.read_excel(uploaded_file, sheet_name="BD")
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}")
        st.stop()

    faltando = validar_planilha(df)
    if faltando:
        st.error(f"Colunas obrigatórias ausentes na aba 'BD': {', '.join(faltando)}")
        st.stop()

    # Garantir que lat/lon são float
    for col in ['LAT E', 'LONG E', 'LAT S', 'LONG S']:
        df[col] = df[col].astype(float)

    # 🔥 ENDEREÇO + BAIRRO (com cache via session_state para evitar re-chamadas)
    cache_key = f"enderecos_{uploaded_file.name}"
    if cache_key not in st.session_state:
        ruas, bairros = [], []
        with st.spinner("Buscando endereços..."):
            for _, row in df.iterrows():
                rua, bairro = obter_endereco_google(float(row['LAT E']), float(row['LONG E']))
                ruas.append(rua)
                bairros.append(bairro)
                time.sleep(0.05)
        st.session_state[cache_key] = (ruas, bairros)

    ruas, bairros = st.session_state[cache_key]
    df["ENDERECO"] = ruas
    df["BAIRRO"] = bairros

    # === ROTAS ===
    grupos = df.groupby("ROTA")
    client = openrouteservice.Client(key=ORS_API_KEY)
    kml_files = []

    for rota_nome, grupo in grupos:

        # Aviso se grupo ultrapassar limite de waypoints
        if len(grupo) > MAX_WAYPOINTS:
            st.warning(
                f"Rota '{rota_nome}' tem {len(grupo)} colaboradores, "
                f"acima do limite de {MAX_WAYPOINTS} waypoints do ORS. "
                f"Apenas os primeiros {MAX_WAYPOINTS} serão usados."
            )
            grupo = grupo.head(MAX_WAYPOINTS)

        # ENTRADA
        pontos_entrada = [[row['LONG E'], row['LAT E']] for _, row in grupo.iterrows()]
        pontos_entrada.append([destino_final[1], destino_final[0]])
        try:
            res = client.directions(
                coordinates=pontos_entrada,
                profile='driving-car',
                optimize_waypoints=True,
                format='geojson'
            )
            coords = res['features'][0]['geometry']['coordinates']
            kml_files.append((f"{rota_nome}_entrada", gerar_kml(grupo, coords, destino_final, "Entrada")))
        except Exception as e:
            st.error(f"Erro entrada {rota_nome}: {e}")

        # SAÍDA
        pontos_saida = [[destino_final[1], destino_final[0]]]
        pontos_saida += [[row['LONG S'], row['LAT S']] for _, row in grupo.iterrows()]
        try:
            res = client.directions(
                coordinates=pontos_saida,
                profile='driving-car',
                optimize_waypoints=True,
                format='geojson'
            )
            coords = res['features'][0]['geometry']['coordinates']
            kml_files.append((f"{rota_nome}_saida", gerar_kml(grupo, coords, destino_final, "Saída")))
        except Exception as e:
            st.error(f"Erro saída {rota_nome}: {e}")

    st.session_state["kmls"] = kml_files
    st.session_state["df"] = df

# === SAÍDA ===
if "kmls" in st.session_state:
    st.subheader("📥 KMLs")
    for nome, kml in st.session_state["kmls"]:
        st.download_button(nome, kml.getvalue(), f"{nome}.kml")

    st.subheader("📊 Relatório")
    df_final = st.session_state["df"]
    st.dataframe(df_final[["COLABORADOR", "ROTA", "ENDERECO", "BAIRRO"]])

    output = io.BytesIO()
    df_final.to_excel(output, index=False)
    output.seek(0)  # FIX: resetar ponteiro para o Excel não sair vazio

    st.download_button(
        "📥 Baixar Excel",
        output.getvalue(),
        "relatorio_rotas.xlsx"
    )
