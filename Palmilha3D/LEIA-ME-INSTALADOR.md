# Palmilha Studio — instalação

## Requisitos

- Windows 10 (versão 1809 ou posterior) ou Windows 11, 64 bits.
- Placa de vídeo e driver com suporte a OpenGL para a visualização 3D.
- Aproximadamente 700 MB livres durante a instalação.

O instalador inclui o aplicativo, Python e as bibliotecas necessárias. Não é preciso instalar Python nem ter conexão com a internet. O runtime oficial do Microsoft Visual C++ também é instalado quando ainda não estiver disponível no computador.

## Preparar e compilar o instalador

1. Instale o Inno Setup 6 e prepare o ambiente do projeto com `INICIAR.bat`.
2. No PowerShell, na pasta do projeto, execute `powershell -ExecutionPolicy Bypass -File .\installer\build-installer.ps1`. Isso monta o aplicativo em `installer\payload\PalmilhaStudio` e valida a inicialização com um `PATH` limpo, sem compilar o instalador.
3. Abra `installer\PalmilhaStudio.iss` no Inno Setup e clique em **Compile**. O instalador será salvo em `installer\output`.

Opcionalmente, para preparar e compilar pelo PowerShell em um único comando, use `powershell -ExecutionPolicy Bypass -File .\installer\build-installer.ps1 -CompileInstaller`.

Se o runtime do Visual C++ ainda não estiver em `installer\redist\vc_redist.x64.exe`, o script baixa o instalador oficial da Microsoft. Essa etapa requer internet uma vez; a instalação final inclui esse runtime e não depende de internet.

## Instalar em outra máquina

1. Execute o instalador gerado em `installer\output`.
2. Aceite a confirmação do Windows para instalar o aplicativo e os componentes necessários.
3. Opcionalmente, marque a criação de um atalho na área de trabalho.
4. Abra o **Palmilha Studio** pelo menu Iniciar ou pelo atalho criado.

O aplicativo processa as imagens localmente. Importe PNG, JPG ou JPEG e exporte os modelos em STL, em milímetros.

## Remover

Use **Configurações > Aplicativos > Aplicativos instalados > Palmilha Studio > Desinstalar**. O runtime compartilhado do Visual C++ permanece instalado para outros aplicativos do computador.
