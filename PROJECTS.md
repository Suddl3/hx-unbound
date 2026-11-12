# HX Unbound project directory

Reviewed November 9, 2026. Repository links and descriptions were checked against live GitHub metadata and project documentation. Hardware results below are attributed to their projects; this directory does not independently certify them.

These are known relevant projects, not a confirmed membership roster or an exhaustive list. The owner column identifies the GitHub repository owner, not sole authorship. Projects retain their own ownership and licenses.

Repositories in the three project tables below are automatically monitored in Discord's **#repo-updates**. Adding a row starts monitoring on the next hourly check, with no historical backlog. The foundational references farther down are not monitored.

<!-- monitored-projects:start -->

## NAM firmware and device extensions

| Project | Repository owner | Purpose and current scope |
| --- | --- | --- |
| [HX Stomp NAM Lite](https://github.com/nocaseguy/hx-stomp-nam-lite) | nocaseguy | NAM A2 Lite firmware tooling for HX Stomp, Stomp XL, and HX Effects on 3.80.0. Foundational NAM kernel and SHARC tooling used by several ports. The README distinguishes current-build testing from earlier device results. |
| [Helix Floor NAM Lite](https://github.com/savedadodo/helix-floor-nam-lite/tree/helix-floor) | savedadodo | Experimental Floor port with device-specific DSP work and setup tooling. The relevant default branch is `helix-floor`. Its README reports Floor hardware results and documents HX Edit preset limitations. |
| [HX Unbound Floor](https://github.com/Suddl3/hx-unbound-floor) | Suddl3 | Custom firmware project for Helix Floor 3.80.0, built on the Floor port above with its commit history. Plans HXtra-style extensions for the Floor: a feature engine for the main program, a metronome, more NAM block options, and presets that stay compatible with HX Edit NAM. Started November 12, 2026: its `main` branch builds the Floor port unchanged and adds no firmware features yet. |
| [Helix LT NAM](https://github.com/andreidevs/helix-lt-nam) | andreidevs | Experimental LT port based on the Floor work. Also contains NAM Studio for capture blending, chaining, refinement, and conversion. The README reports one-device LT testing; multi-block LT capacity remains separately unverified there. |
| [HX Effects NAM Lite](https://github.com/scottlynn73/hx-effects-nam-lite) | scottlynn73 | HX Effects 3.80.0 port and additional Click/metronome and Geiger/bit-crusher work. Retain this attribution even though upstream also supports HX Effects. The branches use different block identities; their presets are not assumed interchangeable. |
| [HXtra](https://github.com/wisemandenny/hxtra) | wisemandenny | Formerly HX Stomp CustomOS. Stomp firmware extensions built from the NAM tooling, including tuner settings, BPM display, DSP budget display, long-press actions, additional snapshots, and boot-screen customization. Separate development direction from the current NAM upstream. |

## NAM editors and capture workflows

| Project | Repository owner | Purpose and current scope |
| --- | --- | --- |
| [HX Unbound Editor](https://github.com/Suddl3/hx-unbound-editor) | Suddl3 | Independent preset editor and capture librarian. Public Windows source preview; development targets original Floor 3.80. Starts offline, with experimental device access opt-in. The published preview disables device capture/IR transfers and verified named NAM selection. A separate project within the broader HX Unbound community. |
| [HX Edit NAM](https://github.com/andreidevs/hx-edit-nam) | andreidevs | Adds NAM browsing/import/conversion and TONE3000 integration around a local HX Edit 3.82 installation. Current documentation targets Helix LT with its NAM firmware and offers Windows x64 and macOS Apple Silicon releases. This is distinct from the independent HX Unbound editor. |

NAM Studio currently lives inside **andreidevs/helix-lt-nam**; it is not listed as a separate repository.

## Related editors and shared transport

These projects are relevant to the ecosystem. Their inclusion does not imply Discord participation or NAM compatibility across all their supported devices.

| Project | Repository owner | Purpose and current scope |
| --- | --- | --- |
| [TonePush](https://github.com/crmne/tonepush) | crmne | Editor, CLI, and reusable USB/protocol/catalog crates. HX Unbound uses pinned portions of these crates. Project hardware coverage and operation-specific support belong in its own documentation. |
| [OpenHX](https://github.com/allansomensi/openhx) | allansomensi | Cross-platform HX tooling and protocol research. Current feature checklist supports setlist/preset listing and selection; full GUI editing and other operations remain planned. Reports navigation validation on Stomp, Stomp XL, and Floor. |
| [ToneRelay](https://github.com/mpeskett88/ToneRelay) | mpeskett88 | Browser/mobile editor using a Raspberry Pi as the USB host. Reports Floor 3.80 verification, with other HX devices listed as future work. Credits TonePush, OpenHX, and helix_usb for related transport/protocol work. |

<!-- monitored-projects:end -->

## Foundational research and NAM projects

| Repository | Owner | Reference role |
| --- | --- | --- |
| [helix_usb](https://github.com/kempline/helix_usb) | kempline | Earlier Python USB communication and HX protocol research. |
| [HelixBackupFiles](https://github.com/AntonyCorbett/HelixBackupFiles) | AntonyCorbett | Helix backup-file parsing reference. |
| [hx-tools](https://github.com/frankdeath/hx-tools) | frankdeath | HX file-format tooling referenced by the editor research. |
| [ghidra-sharc](https://github.com/roblg/ghidra-sharc) | roblg | SHARC processor tooling and assembler-table ancestry credited by the firmware work. |
| [Neural Amp Modeler](https://github.com/sdatkinson/neural-amp-modeler) | sdatkinson | NAM training and model-format foundations. |
| [NeuralAmpModelerCore](https://github.com/sdatkinson/NeuralAmpModelerCore) | sdatkinson | Core NAM DSP library. |
| [NeuralAmpModelerPlugin](https://github.com/sdatkinson/NeuralAmpModelerPlugin) | sdatkinson | NAM plug-in implementation. |

## Relationships that help avoid duplicate work

- The Stomp NAM project is a foundation for the Floor, LT, HX Effects, and HXtra work. Each device/revision still needs its own compatibility evidence.
- The LT port explicitly builds on the Floor implementation.
- HX Unbound Floor builds on the Floor port the way HXtra builds on the Stomp project. Fixes to the Floor's NAM kernel belong with the Floor port first.
- HX Edit NAM and the HX Unbound editor approach desktop editing differently. Shared capture conversion, compatibility findings, and test cases may be useful across both.
- TonePush provides shared transport components used by downstream editors. A transport fix should be compared with current upstream work before being reimplemented.
- HX Effects support exists both upstream and in scottlynn73's project. Preserve both provenance and the distinction between their implementations.

## Corrections and additions

This is a starting directory, not a closed roster. Suggest a project or correction with its repository link, owner or maintainer, purpose, supported hardware, and a source for current status. Maintainers can clarify their preferred descriptions and whether they wish to participate in the community. GitHub names are not assumed to be Discord identities.

Discovery sources include the projects' linked READMEs and the public [Floor/LT collaboration discussion](https://github.com/nocaseguy/hx-stomp-nam-lite/issues/8). The seven foundational entries were checked for live repository availability and reference purpose; they were not audited for current hardware compatibility.
