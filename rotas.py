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

# Upload da planilha
uploaded_file = st.file_uploader("Envie sua planilha LISTA.xlsx", type=["xlsx"])

# Mapa para escolher destino
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

# === FUNÇÃO GOOGLE (ENDEREÇO + BAIRRO) ===

@st.cache_data
def obter_endereco_google(lat, lon):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "latlng": f"{lat},{lon}",
        "key": GOOGLE_API_KEY
    }

    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()

        if data["results"]:
            componentes = data["results"][0]["address_components"]

            rua = bairro = ""

            for comp in componentes:
                if "route" in comp["types"]:
                    rua = comp["long_name"]

                if "sublocality" in comp["types"] or "neighborhood" in comp["types"]:
                    bairro = comp["long_name"]

            return rua, bairro

    return "Não encontrado", "Não encontrado"


# === FUNÇÃO KML ===

def gerar_kml(grupo, coords, destino_final, tipo="Entrada"):
    kml_root = etree.Element('kml', xmlns="http://www.opengis.net/kml/2.2")
    document = etree.SubElement(kml_root, 'Document')

    for _, row in grupo.iterrows():
        placemark = etree.SubElement(document, 'Placemark')
        name = etree.SubElement(placemark, 'name')
        name.text = str(row['COLABORADOR'])

        point = etree.SubElement(placemark, 'Point')
        coordinates = etree.SubElement(point, 'coordinates')

        if tipo == "Entrada":
            coordinates.text = f"{row['LONG E']},{row['LAT E']},0"
        else:
            coordinates.text = f"{row['LONG S']},{row['LAT S']},0"

    # destino
    placemark_dest = etree.SubElement(document, 'Placemark')
    etree.SubElement(placemark_dest, 'name').text = "Destino Final"

    point_dest = etree.SubElement(placemark_dest, 'Point')
    coordinates_dest = etree.SubElement(point_dest, 'coordinates')
    coordinates_dest.text = f"{destino_final[1]},{destino_final[0]},0"

    # linha
    placemark_linha = etree.SubElement(document, 'Placemark')
    etree.SubElement(placemark_linha, 'name').text = f"Caminho ({tipo})"

    style = etree.SubElement(placemark_linha, 'Style')
    linestyle = etree.SubElement(style, 'LineStyle')
    etree.SubElement(linestyle, 'color').text = 'ff0000ff'
    etree.SubElement(linestyle, 'width').text = '4'

    linestring = etree.SubElement(placemark_linha, 'LineString')
    etree.SubElement(linestring, 'tessellate').text = '1'

    coord_elem = etree.SubElement(linestring, 'coordinates')
    coord_elem.text = " ".join([f"{c[0]},{c[1]},0" for c in coords])

    tree = etree.ElementTree(kml_root)
    kml_bytes = io.BytesIO()
    tree.write(kml_bytes, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    return kml_bytes


# === PROCESSAMENTO ===

if uploaded_file and destino_final and st.button("GERAR ROTAS E RELATÓRIO"):

    df = pd.read_excel(uploaded_file, sheet_name="BD")

    # 🔥 ENRIQUECIMENTO (ENDEREÇO + BAIRRO)
    ruas = []
    bairros = []

    with st.spinner("Buscando endereços..."):
        for _, row in df.iterrows():
            lat = row['LAT E']
            lon = row['LONG E']

            rua, bairro = obter_endereco_google(lat, lon)

            ruas.append(rua)
            bairros.append(bairro)

            time.sleep(0.05)

    df["ENDERECO"] = ruas
    df["BAIRRO"] = bairros

    # === ROTAS ===
    grupos = df.groupby("ROTA")
    client = openrouteservice.Client(key=ORS_API_KEY)

    kml_files = []

    for rota_nome, grupo in grupos:

        pontos_entrada = [[row['LONG E'], row['LAT E']] for _, row in grupo.iterrows()]
        pontos_entrada.append([destino_final[1], destino_final[0]])

        try:
            resultado = client.directions(
                coordinates=pontos_entrada,
                profile='driving-car',
                optimize_waypoints=True,
                format='geojson'
            )

            coords = resultado['features'][0]['geometry']['coordinates']

            kml = gerar_kml(grupo, coords, destino_final, "Entrada")
            kml_files.append((f"{rota_nome}_entrada", kml))

        except Exception as e:
            st.error(f"Erro na rota {rota_nome}: {e}")

    st.session_state["kmls"] = kml_files
    st.session_state["df_final"] = df


# === SAÍDA ===

if "kmls" in st.session_state:

    st.subheader("📥 KMLs")
    for nome, kml in st.session_state["kmls"]:
        st.download_button(
            label=f"Baixar {nome}.kml",
            data=kml.getvalue(),
            file_name=f"{nome}.kml"
        )

    st.subheader("📊 Relatório")

    df_final = st.session_state["df_final"]

    st.dataframe(df_final[["COLABORADOR", "ROTA", "ENDERECO", "BAIRRO"]])

    output = io.BytesIO()
    df_final.to_excel(output, index=False)

    st.download_button(
        label="📥 Baixar Relatório Excel",
        data=output.getvalue(),
        file_name="relatorio_rotas.xlsx"
    )
