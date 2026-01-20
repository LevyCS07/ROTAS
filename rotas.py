import streamlit as st
import pandas as pd
import openrouteservice
from lxml import etree
import folium
from streamlit_folium import st_folium
import io

# === CONFIGURAÇÕES ===
ORS_API_KEY = "5b3ce3597851110001cf624831819d355127423cb4da08dbf33c6ca0"

st.title("🚗 Gerador de Rotas KML")

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

# Botão para gerar rotas
if uploaded_file and destino_final:
    if st.button("GERAR ROTAS"):
        df = pd.read_excel(uploaded_file, sheet_name="BD")
        grupos = df.groupby("ROTA")
        client = openrouteservice.Client(key=ORS_API_KEY)

        m = folium.Map(location=destino_final, zoom_start=12)
        kml_files = []

        for rota_nome, grupo in grupos:
            pontos = [[row['LONG'], row['LAT']] for _, row in grupo.iterrows()]
            pontos.append([destino_final[1], destino_final[0]])

            try:
                resultado = client.directions(
                    coordinates=pontos,
                    profile='driving-car',
                    optimize_waypoints=True,
                    format='geojson'
                )
            except Exception as e:
                st.error(f"Erro na rota {rota_nome}: {e}")
                continue

            coords = resultado['features'][0]['geometry']['coordinates']
            folium.PolyLine([(c[1], c[0]) for c in coords], color="blue", weight=4).add_to(m)

            for _, row in grupo.iterrows():
                folium.Marker([row['LAT'], row['LONG']], popup=row['COLABORADOR']).add_to(m)

            folium.Marker(destino_final, popup="Destino Final", icon=folium.Icon(color="red")).add_to(m)

            # gerar KML
            kml_root = etree.Element('kml', xmlns="http://www.opengis.net/kml/2.2")
            document = etree.SubElement(kml_root, 'Document')

            for _, row in grupo.iterrows():
                placemark = etree.SubElement(document, 'Placemark')
                name = etree.SubElement(placemark, 'name')
                name.text = str(row['COLABORADOR'])
                point = etree.SubElement(placemark, 'Point')
                coordinates = etree.SubElement(point, 'coordinates')
                coordinates.text = f"{row['LONG']},{row['LAT']},0"

            placemark_destino = etree.SubElement(document, 'Placemark')
            name_dest = etree.SubElement(placemark_destino, 'name')
            name_dest.text = "Destino Final"
            point_dest = etree.SubElement(placemark_destino, 'Point')
            coordinates_dest = etree.SubElement(point_dest, 'coordinates')
            coordinates_dest.text = f"{destino_final[1]},{destino_final[0]},0"

            placemark_linha = etree.SubElement(document, 'Placemark')
            name_linha = etree.SubElement(placemark_linha, 'name')
            name_linha.text = "Caminho"
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
            kml_files.append((rota_nome, kml_bytes))

        # salvar no estado da sessão
        st.session_state["mapa"] = m
        st.session_state["kmls"] = kml_files

# exibir mapa e botões se já existem no estado
if "mapa" in st.session_state:
    st_folium(st.session_state["mapa"], height=500, width=700)

if "kmls" in st.session_state:
    for rota_nome, kml_bytes in st.session_state["kmls"]:
        st.download_button(
            label=f"Baixar rota {rota_nome}.kml",
            data=kml_bytes.getvalue(),
            file_name=f"rota_{rota_nome}.kml",
            mime="application/vnd.google-earth.kml+xml"
        )



