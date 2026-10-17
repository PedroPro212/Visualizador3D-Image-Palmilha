# Palmilha Studio

Aplicativo desktop local para transformar a silhueta de uma imagem em uma palmilha 3D suave e exportar STL em milímetros. Interface em português com Qt e visualização OpenGL.

## Iniciar

Abra `INICIAR.bat`. É necessário Python 3.11 a 3.14, 64 bits (recomendado: 3.12). O iniciador procura instalações compatíveis e cria `.venv-studio` separadamente do ambiente antigo. A primeira execução instala as dependências e precisa de internet. As próximas abrem direto, sem reinstalar pacotes. Se disponível, o Python 3.12 do runtime local do Codex também pode ser utilizado.

## Fluxo

1. Importe ou arraste PNG/JPG/JPEG. Use uma foto vista de cima, fundo uniforme e sem sombras, ou PNG transparente. A imagem é processada localmente e não é enviada a serviços externos.
2. Confira a aba **Contorno detectado**. A maior região conectada é preservada; furos internos são preenchidos. Imagens horizontais são giradas para definir o comprimento. Confira ponta e calcanhar.
3. Se necessário, selecione **Marcar contorno**, clique ao redor da palmilha na imagem original e pressione **Concluir**. **Restaurar detecção automática** descarta os pontos manuais.
4. Informe o comprimento real em mm. Ajuste espessura, calcanhar, arco e lado. Os ajustes atualizam o modelo automaticamente. Suavização maior arredonda pequenas irregularidades e pode remover detalhes; valores menores preservam mais o contorno.
5. Arraste para girar, use a roda para zoom e Ctrl + arraste para deslocar. Há vistas superior/lateral, três materiais e exibição da malha.
6. Clique **Exportar STL** quando o indicador informar que o modelo está atualizado. A exportação fica indisponível enquanto há alterações pendentes. STL não guarda unidades: selecione milímetros no CAD/fatiador.

## Geometria e desempenho

O contorno é extraído em até 900 px, reamostrado e suavizado com filtro periódico. A triangulação restrita respeita as concavidades e acrescenta vértices internos; a base e as paredes fecham a malha. O comprimento informado é mantido após a suavização. A largura acompanha a proporção da imagem.

Qt/OpenGL mantém a malha na visualização acelerada por hardware, com normais interpoladas. Geração ocorre em uma fila de trabalho separada da interface. Ajustes próximos são agrupados por 220 ms, resultados antigos são descartados e a máscara é reutilizada quando somente as medidas mudam. Não há laço de redesenho contínuo enquanto a cena está parada. Desempenho depende de GPU/driver, imagem e dimensões; não há garantia universal de FPS.

Uma única imagem não contém as alturas reais. O resultado preserva a silhueta e usa uma superfície paramétrica para arco e calcanhar. Não há reconstrução fotogramétrica, correção de perspectiva, cópia de textura ou reprodução do algoritmo proprietário do GenSole. Para uso funcional, as medidas e a forma exigem validação apropriada.

## Validação

` .venv-studio\Scripts\python.exe -m unittest test_core -v `

Testes verificam fechamento, orientação, escala, transparência, seleção manual, preservação de concavidades e escrita do STL. `test_ui.py` exercita a interface com uma janela temporária e salva uma captura somente se `PALMILHA_SCREENSHOT` estiver definido.
