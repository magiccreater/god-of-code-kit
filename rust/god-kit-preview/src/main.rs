use std::env;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Command, ExitCode};

fn main() -> ExitCode {
    let args: Vec<_> = env::args_os().skip(1).collect();
    match args.first().and_then(|arg| arg.to_str()) {
        Some("-V" | "--version") => {
            println!("god-kit-preview {}", env!("CARGO_PKG_VERSION"));
            return ExitCode::SUCCESS;
        }
        Some("-h" | "--help") => {
            print_help();
            return ExitCode::SUCCESS;
        }
        _ if args.is_empty() => {
            print_help();
            return ExitCode::SUCCESS;
        }
        _ => {}
    }

    let Some(kit_dir) = env::var_os("GOD_KIT_DIR")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
    else {
        eprintln!(
            "god-kit-preview: set GOD_KIT_DIR to the absolute path of your WSL kit checkout."
        );
        return ExitCode::from(2);
    };

    let launcher = kit_dir.join("god");
    let error = Command::new(&launcher).args(args).exec();
    eprintln!(
        "god-kit-preview: could not run {}: {error}",
        launcher.display()
    );
    ExitCode::FAILURE
}

fn print_help() {
    println!(
        "Usage: god-kit-preview <god command and arguments>\n\
         Set GOD_KIT_DIR to the absolute path of a God of Code Kit checkout in WSL.\n\
         The preview runs that checkout's god launcher from your current directory.\n\
         Run god-kit-preview --version to see the preview version."
    );
}
