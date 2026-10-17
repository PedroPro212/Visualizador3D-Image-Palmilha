# Palmilha3D

Aplicativo desktop em Python com interface em português. Importa JPG, JPEG e PNG, extrai a silhueta, cria um volume com base plana e permite girar, ampliar e exportar STL em milímetros. Funciona localmente; as imagens não são enviadas para serviços externos.

## Executar no Windows

Instale Python 3.11 ou superior, incluindo Tcl/Tk e Python Launcher. Extraia toda a pasta e abra `INICIAR.bat`. Na primeira execução, a conexão com a internet é necessária para instalar as dependências em um ambiente virtual dentro desta pasta.

Alternativa pelo terminal nesta pasta:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

## Usar

1. O aplicativo inicia com uma silhueta demonstrativa. Abra uma foto da palmilha vista de cima, sobre fundo uniforme, sem sombras, objetos ou textos. PNG com transparência também é aceito.
2. Oriente a ponta para cima e o calcanhar para baixo. Imagens horizontais são giradas automaticamente; confira o resultado e use **Inverter ponta e calcanhar** se necessário. O eixo mais longo é considerado o comprimento; não há correção de perspectiva.
3. Ajuste a tolerância de separação do fundo. Se necessário, use **Marcar contorno manual**, clique sequencialmente ao redor da borda na miniatura e pressione **Concluir contorno**. A seleção usa a imagem original como referência e é fechada automaticamente. Para recomeçar, clique novamente em Marcar contorno manual. Reabra a imagem para voltar à detecção automática.
4. Informe o comprimento real e ajuste a espessura mínima e as elevações adicionais do calcanhar e do arco. O lado escolhido move o arco para a região medial correspondente; confira visualmente. Clique em **Gerar / atualizar 3D**.
5. Arraste a visualização para girar e use a roda do mouse para ampliar. Os botões Superior e Lateral permitem conferir o perfil.
6. Exporte STL para abrir em um programa de CAD ou fatiador. Selecione milímetros ao importar: o formato STL não armazena a unidade.

## Como o modelo é gerado

A detecção automática estima a cor do fundo pelos cantos e mantém a maior região conectada, preenchendo furos. O contorno é amostrado em uma grade de 72 células de comprimento. A largura acompanha a proporção da silhueta. A superfície superior recebe elevações suaves parametrizadas; paredes laterais e base fecham a malha. Bordas podem apresentar discretização visível. Esta versão prioriza uma prévia editável e exportação simples; não implementa edição CAD de curvas ou reconstrução fotogramétrica.

Uma imagem isolada não revela a altura real nem a anatomia do pé. As elevações são parâmetros geométricos, não medições extraídas da foto. Este aplicativo não replica o algoritmo do GenSole nem fornece prescrição ortopédica. A fabricação e o uso de uma palmilha funcional precisam de medidas e validação apropriadas.

## Arquivos

- `app.py`: interface e visualização 3D em Tkinter.
- `core.py`: contorno, geração de malha e STL binário.
- `test_core.py`: verificações de fechamento, orientação, escala e exportação.
- `exemplo.png` e `exemplo.stl`: demonstração pronta para conferir.

Teste do núcleo: `python -m unittest test_core -v`.
