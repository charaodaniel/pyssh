Name:           pyssh
Version:        0.1.0
Release:        1%{?dist}
Summary:        Localiza dispositivos SSH na rede local e abre sessões
License:        MIT
URL:            https://github.com/charaodaniel/pyssh
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.9, python3-tkinter, openssh-clients

%description
O pyssh varre a rede local por portas SSH (padrão 8022, cenário Termux/Android),
mantém conexões salvas, chaves e histórico de atividades, e abre sessões em
um terminal do sistema. Inclui a interface gráfica (pyssh) e a linha de
comando (pyssh-cli). Somente biblioteca padrão do Python.

%prep
%setup -q

%build
# Aplicação pura em Python — nada a compilar.

%install
install -d %{buildroot}/usr/lib/pyssh
cp -r pyssh %{buildroot}/usr/lib/pyssh/pyssh
install -m644 main.py cli.py LICENSE README.md %{buildroot}/usr/lib/pyssh/
find %{buildroot} \( -name '__pycache__' -o -name '*.pyc' \) -prune -exec rm -rf {} + 2>/dev/null || true

install -Dm755 packaging/wrappers/pyssh     %{buildroot}%{_bindir}/pyssh
install -Dm755 packaging/wrappers/pyssh-cli %{buildroot}%{_bindir}/pyssh-cli
install -Dm644 packaging/pyssh.desktop %{buildroot}%{_datadir}/applications/pyssh.desktop
install -Dm644 packaging/icons/pyssh-256.png %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/pyssh.png
install -Dm644 packaging/icons/pyssh-128.png %{buildroot}%{_datadir}/icons/hicolor/128x128/apps/pyssh.png
install -Dm644 packaging/icons/pyssh-48.png  %{buildroot}%{_datadir}/icons/hicolor/48x48/apps/pyssh.png

%files
%license LICENSE
%doc README.md
/usr/lib/pyssh/*
%{_bindir}/pyssh
%{_bindir}/pyssh-cli
%{_datadir}/applications/pyssh.desktop
%{_datadir}/icons/hicolor/*/apps/pyssh.png
