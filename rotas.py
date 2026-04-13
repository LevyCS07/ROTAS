import streamlit as st
import pandas as pd
import openrouteservice
from lxml import etree
import folium
from streamlit_folium import st_folium
import io

# === CONFIGURAÇÕES ===
ORS_API_KEY = st.secrets["ORS_API_KEY"]

st.title("🚗 Gerador de Rotas KML (Entrada e Saída)")

# Upload da planilha
uploaded_file = st.file_uploader("Envie sua planilha LISTA.xlsx", type=["xlsx"])

# Mapa inicial para escolher destino
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

def gerar_kml(grupo, coords, destino_final, tipo="Entrada"):
    kml_root = etree.Element('kml', xmlns="http://www.opengis.net/kml/2.2")
    document = etree.SubElement(kml_root, 'Document')

    # pontos do grupo
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
    placemark_destino = etree.SubElement(document, 'Placemark')
    name_dest = etree.SubElement(placemark_destino, 'name')
    name_dest.text = "Destino Final"
    point_dest = etree.SubElement(placemark_destino, 'Point')
    coordinates_dest = etree.SubElement(point_dest, 'coordinates')
    coordinates_dest.text = f"{destino_final[1]},{destino_final[0]},0"

    # linha da rota
    placemark_linha = etree.SubElement(document, 'Placemark')
    name_linha = etree.SubElement(placemark_linha, 'name')
    name_linha.text = f"Caminho ({tipo})"
    style = etree.SubElement(placemark_linha, 'Style')
    linestyle = etree.SubElement(style, 'LineStyle')
    etree.SubElement(linestyle, 'color').text = 'ff0000ff'
    etree.SubElement(linestyle, 'width').text = '4'
    linestring = etree.SubElement(placemark_linha, 'LineString')
    etree.SubElement(linestring, 'extrude').text = '1'
    etree.SubElement(linestring, 'tessellate').text = '1'
    etree.SubElement(linestring, 'altitudeMode').text = 'clampToGround'
    coord_elem = etree.SubElement(linestring, 'coordinates')
    coord_elem.text = " ".join([f"{c[0]},{c[1]},0" for c in coords])

    tree = etree.ElementTree(kml_root)
    kml_bytes = io.BytesIO()
    tree.write(kml_bytes, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return kml_bytes

# Botão para gerar rotas
if uploaded_file and destino_final and st.button("GERAR ROTAS"):
    try:
        df = pd.read_excel(uploaded_file, sheet_name="BD")
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}")
        st.stop()

    grupos = df.groupby("ROTA")
    client = openrouteservice.Client(key=ORS_API_KEY)

    kml_files = []

    for rota_nome, grupo in grupos:
        # --- Rota de entrada ---
        pontos_entrada = [[row['LONG E'], row['LAT E']] for _, row in grupo.iterrows()]
        pontos_entrada.append([destino_final[1], destino_final[0]])

        try:
            resultado_entrada = client.directions(
                coordinates=pontos_entrada,
                profile='driving-car',
                optimize_waypoints=True,
                format='geojson'
            )
            coords_entrada = resultado_entrada['features'][0]['geometry']['coordinates']
            kml_bytes_entrada = gerar_kml(grupo, coords_entrada, destino_final, tipo="Entrada")
            kml_files.append((f"{rota_nome}_entrada", kml_bytes_entrada))
        except Exception as e:
            st.error(f"Erro na rota de entrada {rota_nome}: {e}")

        # --- Rota de saída ---
        pontos_saida = [[destino_final[1], destino_final[0]]]
        pontos_saida += [[row['LONG S'], row['LAT S']] for _, row in grupo.iterrows()]

        try:
            resultado_saida = client.directions(
                coordinates=pontos_saida,
                profile='driving-car',
                optimize_waypoints=True,
                format='geojson'
            )
            coords_saida = resultado_saida['features'][0]['geometry']['coordinates']
            kml_bytes_saida = gerar_kml(grupo, coords_saida, destino_final, tipo="Saída")
            kml_files.append((f"{rota_nome}_saida", kml_bytes_saida))
        except Exception as e:
            st.error(f"Erro na rota de saída {rota_nome}: {e}")

    st.session_state["kmls"] = kml_files

# mostrar botões de download
if "kmls" in st.session_state:
    st.subheader("📥 Downloads disponíveis")
    for rota_nome, kml_bytes in st.session_state["kmls"]:
        st.download_button(
            label=f"Baixar {rota_nome}.kml",
            data=kml_bytes.getvalue(),
            file_name=f"{rota_nome}.kml",
            mime="application/vnd.google-earth.kml+xml"
        )

        )












