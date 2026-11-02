# Homebrew formula for shellcopy. It lives in the tap repo github.com/Chuwee/homebrew-shellcopy as
# Formula/shellcopy.rb; packaging/homebrew/update-formula.sh fills in url and sha256 for a release.
class Shellcopy < Formula
  desc "Copy part of your terminal's output with the keyboard"
  homepage "https://github.com/Chuwee/shellcopy"
  url "https://github.com/Chuwee/shellcopy/archive/refs/tags/v0.1.2.tar.gz"
  sha256 "94b6450035a31c567e65c658639edd72d279614d2b4b780a727f887edac20941"
  license "MIT"

  depends_on "python@3.13"

  # Pure-Python dependencies, copied in as source rather than built, so no virtualenv or build backend is needed.
  resource "pyte" do
    url "https://files.pythonhosted.org/packages/ab/ab/b599762933eba04de7dc5b31ae083112a6c9a9db15b01d3109ad797559d9/pyte-0.8.2.tar.gz"
    sha256 "5af970e843fa96a97149d64e170c984721f20e52227a2f57f0a54207f08f083f"
  end

  resource "wcwidth" do
    url "https://files.pythonhosted.org/packages/ea/01/e5ac23733628a6bbb91913a765fcf55ee8070d8d991bc88fdaaf805052c7/wcwidth-0.9.4.tar.gz"
    sha256 "fd8d57d3cdfe570e3265c8fab1885c24e34ef40889c0759c0c304a19e9835954"
  end

  def install
    libexec.install "shellcopy.py"
    # shellcopy.py adds the vendor directory next to it to its import path.
    resources.each do |r|
      r.stage { (libexec/"vendor").install r.name }
    end
    python = Formula["python@3.13"].opt_bin/"python3.13"
    # opt_ paths, so the shell hook printed by `shellcopy init` keeps working across upgrades.
    (bin/"shellcopy").write <<~SH
      #!/bin/sh
      SHELLCOPY_EXE="#{opt_bin}/shellcopy" exec "#{python}" "#{opt_libexec}/shellcopy.py" "$@"
    SH
    bin.install_symlink "shellcopy" => "cy"
  end

  def caveats
    <<~EOS
      `cy` works from any shell as is: `cmd | cy`. To let plain `cy` pick from what the terminal shows
      (scrollback included), add the hook to your shell's rc file:
        zsh  (~/.zshrc):   #{Utils.safe_popen_read(opt_bin/"shellcopy", "init", "--rc-line", "zsh").strip}
        bash (~/.bashrc):  #{Utils.safe_popen_read(opt_bin/"shellcopy", "init", "--rc-line", "bash").strip}
        fish (~/.config/fish/conf.d/shellcopy.fish):
          #{Utils.safe_popen_read(opt_bin/"shellcopy", "init", "--rc-line", "fish").strip}
      Recording the terminal needs util-linux `script`, so on macOS plain `cy` reads tmux's screen or
      offers to re-run your last command instead.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/shellcopy --version")
    assert_match "shellcopy()", shell_output("#{bin}/shellcopy init bash")
    assert_match "pyte", shell_output("#{Formula["python@3.13"].opt_bin}/python3.13 -c 'import sys; " \
                                      "sys.path.insert(0, \"#{libexec}/vendor\"); import pyte; print(pyte.__name__)'")
  end
end
