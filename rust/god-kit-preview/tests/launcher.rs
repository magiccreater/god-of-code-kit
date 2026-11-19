use std::env;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::process::{self, Command};
use std::time::{SystemTime, UNIX_EPOCH};

#[test]
fn prints_version_without_a_kit_checkout() {
    let output = Command::new(env!("CARGO_BIN_EXE_god-kit-preview"))
        .arg("--version")
        .env_remove("GOD_KIT_DIR")
        .output()
        .unwrap();

    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        concat!("god-kit-preview ", env!("CARGO_PKG_VERSION"), "\n")
    );
}

#[test]
fn forwards_arguments_and_preserves_working_directory_and_exit_status() {
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
    let kit = env::temp_dir().join(format!(
        "god-kit-test-{}-{}",
        process::id(),
        stamp.as_nanos()
    ));
    let project = kit.join("project");
    fs::create_dir(&kit).unwrap();
    fs::create_dir(&project).unwrap();
    let launcher = kit.join("god");
    fs::write(
        &launcher,
        "#!/bin/sh\npwd -P\nprintf '%s\\n' \"$@\"\nexit 23\n",
    )
    .unwrap();
    fs::set_permissions(&launcher, fs::Permissions::from_mode(0o700)).unwrap();

    let expected_path = project.canonicalize().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_god-kit-preview"))
        .env("GOD_KIT_DIR", &kit)
        .current_dir(&project)
        .args(["task", "Change a file; keep the brief intact", "--single"])
        .output();
    fs::remove_dir_all(&kit).unwrap();
    let output = output.unwrap();

    assert_eq!(output.status.code(), Some(23));
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        format!(
            "{}\ntask\nChange a file; keep the brief intact\n--single\n",
            expected_path.display()
        )
    );
}
