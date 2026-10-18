# Palmilha Studio

Aplicativo desktop local para transformar a silhueta de uma imagem em uma palmilha 3D suave e exportar STL em milímetros. Interface em português com Qt e visualização OpenGL.

## Iniciar

Abra `INICIAR.bat`. É necessário Python 3.11 a 3.14, 64 bits (recomendado: 3.12). O iniciador procura instalações compatíveis e cria `.venv-studio` separadamente do ambiente antigo. A primeira execução instala as dependências e precisa de internet. As próximas abrem direto, sem reinstalar pacotes. Se disponível, o Python 3.12 do runtime local do Codex também pode ser utilizado.

## Fluxo

1. Importe ou arraste PNG/JPG/JPEG. Use uma foto vista de cima, fundo uniforme e sem sombras, ou PNG transparente. A imagem é processada localmente e não é enviada a serviços externos.
2. Confira a aba **Contorno detectado**. A maior região conectada é preservada; furos internos são preenchidos. Imagens horizontais são giradas para definir o comprimento. Confira ponta e calcanhar.
3. Se necessário, selecione **Marcar contorno**, clique ao redor da palmilha na imagem original e pressione **Concluir**. **Restaurar detecção automática** descarta os pontos manuais.
4. Informe o comprimento real em mm. Ajuste espessura, calcanhar, arco e lado. **Palmilha plana (sem elevação)** conserva o contorno e a espessura mínima, mas remove o arco, a elevação do calcanhar e o relevo SoleMorph. Os ajustes atualizam o modelo automaticamente. Suavização maior arredonda pequenas irregularidades e pode remover detalhes; valores menores preservam mais o contorno.
5. Arraste para girar, use a roda para zoom e Ctrl + arraste para deslocar. Há vistas superior/lateral, três materiais e exibição da malha.
6. Clique **Exportar STL** quando o indicador informar que o modelo está atualizado. A exportação fica indisponível enquanto há alterações pendentes. STL não guarda unidades: selecione milímetros no CAD/fatiador.

## Pé e mapa de pressão

No seletor acima da visualização, escolha **Pé 3D** para exibir um relevo anatômico sobre a palmilha. O contorno acompanha exatamente a malha da palmilha, incluindo comprimento e largura. Volume do peito do pé, tornozelo e relevo dos dedos podem ser ajustados nos controles. O modelo é uma referência visual paramétrica; ele não é uma digitalização do pé e não é incluído no STL da palmilha.

Escolha **Pressão estimada** para ver um mapa de cores na superfície da palmilha. Os controles ajustam a intensidade relativa no calcanhar, mediopé, metatarsos e dedos. A distribuição é uma ilustração ajustável, não uma medição de pressão plantar. Medidas reais exigem sensores ou uma palmilha instrumentada e validação profissional.

## SoleMorph: palmilha moldada pelo scan

Primeiro carregue a imagem/contorno da palmilha; em seguida use **Importar pé 3D (STL)**. O scan é mantido separado da palmilha. A opção **Moldar a palmilha ao scan** altera a superfície superior da malha da palmilha, preservando o contorno escolhido, a base e a malha fechada para exportação. Desmarque-a para voltar à forma base.

Ajuste a escala e a folga do scan. **Planos de leitura**, **Início** e **Espaçamento entre planos** controlam a faixa plantar usada na conformação. **Posição X/Y** e **Rotação do scan** alinham o scan com a palmilha. **Suavização da superfície** reduz irregularidades do scan, **Transição suave** mistura o relevo com o restante da palmilha, e **Intensidade do relevo** controla quanto o scan eleva o topo; os mesmos ajustes reposicionam a visualização do pé. **Mostrar pé** alterna o scan na visualização sem incluí-lo no STL. **Mapa SoleMorph** colore a superfície pela altura real da forma gerada; ele não representa pressão medida. O mapa **Pressão estimada** continua ilustrativo e ajustável.

O scan deve estar deitado, com o comprimento no eixo Y, altura no Z e a sola voltada para -Z. STL não registra unidade; confira a escala e as dimensões reais antes de imprimir. O modelo gerado é uma aproximação geométrica da superfície plantar e deve ser inspecionado no visualizador e no fatiador antes da fabricação.

## Geometria e desempenho

O contorno é extraído em até 900 px, reamostrado e suavizado com filtro periódico. A triangulação restrita respeita as concavidades e acrescenta vértices internos; a base e as paredes fecham a malha. O comprimento informado é mantido após a suavização. A largura acompanha a proporção da imagem.

Qt/OpenGL mantém a malha na visualização acelerada por hardware, com normais interpoladas. Geração ocorre em uma fila de trabalho separada da interface. Ajustes próximos são agrupados por 220 ms, resultados antigos são descartados e a máscara é reutilizada quando somente as medidas mudam. Não há laço de redesenho contínuo enquanto a cena está parada. Desempenho depende de GPU/driver, imagem e dimensões; não há garantia universal de FPS.

Uma única imagem não contém as alturas reais. O resultado preserva a silhueta e usa uma superfície paramétrica para arco e calcanhar. Não há reconstrução fotogramétrica, correção de perspectiva, cópia de textura ou reprodução do algoritmo proprietário do GenSole. Para uso funcional, as medidas e a forma exigem validação apropriada.

## Validação

` .venv-studio\Scripts\python.exe -m unittest test_core -v `

Testes verificam fechamento, orientação, escala, transparência, seleção manual, preservação de concavidades e escrita do STL. `test_ui.py` exercita a interface com uma janela temporária e salva uma captura somente se `PALMILHA_SCREENSHOT` estiver definido.
