# 保存済みRISC-V NodeでのJS回帰テスト

専用ブランチ: `validation/issue-66803-js-regression`。
追加するのは `.github/workflows/issue-66803-js-regression.yml` とこのディレクトリだけ。
既存workflow、Node/V8の実装、既存テストは変更しない。configure、make、addon生成も実行しない。
pushとActionsの実行はレビュー・承認後に行う。

## バイナリとソースの対応

- fork: <https://github.com/inoway46/node>
- 元job: <https://github.com/inoway46/node/actions/runs/39183959521/job/117842362994>
- artifact: `issue-66803-temporal-full-build` / ID `12165443477`
- 関連Issue: <https://github.com/nodejs/node/issues/66803>
- テスト対象ソース: base `f59539b514344ed0a0945f8790d61121df88a5d4` に、
  artifactの `final-applied.patch` を**1回だけ**適用したもの。
- 元workflow SHA `6ae176d001815235f2d5f5eecdad2c4b2aa0dab5` はテスト対象のSHAではない。
  workflow側checkoutの `test/` や `tools/test.py` は使用しない。

実物の `conditions.json`、`node-bundle.json`、両patchを確認した。
`applied.patch` と `final-applied.patch` は同一で、#66804、#66823、
MutablePage /64候補、4箇所のCappedTag候補の累積差分を含む。
個別patchを追加適用しない。クリーンなbaseの別worktreeへ復元し、
`git diff --binary` 自体のSHA-256も保存済みpatchと照合する。

| 対象 | 確認したSHA-256 |
| --- | --- |
| 元artifact ZIP | `890f4cb79f79de4ab83c5082ab79162472773f35e503e9c01591c24fdc702844` |
| node-runtime.tar.gz | `558260c17b64375398f52ed7a2da6e44f99858f8551e3b071cf7c566e9e158bb` |
| 両累積patch | `26d23edc44b38bb9a82ba32505ff6ba4f08ffd514d05144811a2607a95dc7bd7` |
| Node ELF | `cca346fd8e38298630c715791efcc7ba4be50768ff64467da97e58e11d8b005c` |
| config.gypi | `59eff2cb086cb7a7d5a99c43dd6a9be9a618851d5316d72fb928b97eeb7106b0` |

workflowはtar、両patch、Node、configのハッシュを強制照合する。
tarにはNode、config、manifest、smoke.js、runtimeの6つのELFライブラリだけがある。
テスト、cctest、addon生成物は入っていない。2026-10-20のAPI確認では未失効、
有効期限は2027-01-17。削除・失効した場合はダウンロード段階で失敗し、再ビルドへ切り替えない。

## 起動条件と事前検証

Ubuntu 24.04の1ジョブで `qemu-user-static` とbinfmtを設定し、登録のenabledとFフラグを確認する。
`QEMU_CPU=rv64,v=false,zba=false,zbb=false,zbc=false,zbs=false` を固定。
`QEMU_LD_PREFIX` で保存済みruntimeを指定し、
`QEMU_SET_ENV=LD_LIBRARY_PATH=<bundle>/runtime/lib` でゲストのライブラリ探索を設定する。
ホスト用 `LD_LIBRARY_PATH` へRISC-Vライブラリを設定しない。

Node ELFを復元ソースの `out/Release/node` に配置し、これを絶対パスで直接実行する。
RISC-V ELF64とバイナリハッシュの確認に加えて、次を先に検証する。

1. 直接実行、`process.arch === 'riscv64'`、`process.execPath` が配置したELFであること。
2. `spawnSync(process.execPath, ...)` で同じarchとexecPathを得ること。
3. `fork(..., { execPath: process.execPath })` のIPCと正常終了。
4. `worker_threads` の起動、メッセージ、正常終了。
5. `--harmony-temporal` でTemporalが利用できること。

失敗時は本テストを実行しない。起動失敗の原因が環境かバイナリかはログで切り分ける。
`tools/test.py --shell` にはこのELFの絶対パスだけを渡す。
QEMU引数入り文字列や `--special-command` に依存しない。
PATHの先頭にも同じELFのディレクトリを置き、ドライバーはホストNodeへフォールバックしない。

## 初回のテスト一覧

`scope=small` の既定セットは次の15本。すべて復元ソースの `test/parallel/` に実在する。
本体、common、参照fixtureを確認し、これらの実行に別途生成するaddonやC++ helperは見つからなかった。

| 群 | テスト名（拡張子を除く） |
| --- | --- |
| Buffer / JSON | `test-buffer-alloc`, `test-buffer-compare`, `test-buffer-tojson` |
| 文字列 | `test-string-decoder`, `test-string-decoder-end` |
| JSON読込エラー | `test-require-json` |
| 基本fs | `test-fs-exists`, `test-fs-readfile-empty`, `test-fs-readfile-fd` |
| worker | `test-worker-message-channel` |
| child_process | `test-child-process-fork`, `test-child-process-fork-exec-argv` |
| Temporal | `test-temporal`, `test-temporal-with-zoneinfo`, `test-fs-stat-temporal` |

通常の12本とTemporalの3本を別々に `tools/test.py` で実行する。
後者だけ `--node-args=--harmony-temporal` を追加する。
Temporalのビルド条件、zoneinfoのsmall ICU条件、fsのタイムスタンプ条件など、
テスト固有のskipを尊重する。選んだ15本に独自の `// Flags:` はないが、
拡張時も既存ランナーによるFlagsとstatus規則をそのまま使う。
JITや機能の一括無効化、テスト内容の変更、繰り返し測定は行わない。

実行オプションは `-j 1 --timeout=300 --progress=tap --verbose --report --time --flaky-tests=run`。
x64ホスト上の元ランナーのrelease倍率は1なので、通常の1テスト当たり300秒。
ツール内部の初期探査も含め、smallの各群に1800秒の外側タイムアウトを置く。
事前検証の各コマンドは180秒、事前検証stepは10分、ジョブ全体は180分が上限。

初回は準備込みで**5〜20分程度を見込むが、QEMUでの実測前の目安**。
遅延・ハング時はsmallの2群がそれぞれ30分で打ち切られる。

## 範囲の拡張と不足する生成物

dispatchの `scope` で `small` → `parallel` → `sequential` / `message` の順に拡張できる。
`js-suites` はこの3suiteを1回のランナー起動で指定する。いずれも並列度1のまま。
拡張範囲は数十分〜数時間を見込み、1回のランナーは8400秒（140分）で打ち切る。
完走できなければTAPのplanとcompleted、外側timeoutで未完走と分かる。
`make test-ci` や全CIを実行する構成ではない。

拡張先のJSテストにもネイティブ依存がある。例えば、同じビルド設定で生成した
`test/addons/**/build/Release/*.node`、fixture用の実行ファイル・共有ライブラリ、
embedding/SEA/snapshot関連helper、`out/Release/cctest` などはこのartifactにない。
必要な種類は選択テストに依存し、cctest自体はこのworkflowのsuiteには含めない。

`selected-tests.json` に実行候補、Flags、ネイティブ依存の静的な手掛かりを記録する。
これは間接依存を含む完全な依存解析ではない。失敗ログに存在しない `.node` や
helperのENOENTがあれば、`possible_missing_prerequisites` に調査候補として保存する。
候補を自動skipや成功に変換しない。実際の不足パスと必要な生成物を確認して報告し、
追加クロスビルドは別途相談する。assertion、クラッシュ、timeoutと同一原因だと決めつけない。

## 承認後のpushと手動実行

**現時点でpush、commit、workflow dispatchは行っていない。**

実行時の `GITHUB_TOKEN` は `contents: read` と `actions: read` のみ。
元runのartifact読込にactions権限が必要。外部secretや書込トークンはworkflowへ渡さない。
runner上でaptとbinfmtの設定にsudoを使う。
pushする人にはforkのcontents/workflow変更権限、dispatchする人にはforkのActions実行権限が必要。
classic PATを使う場合はリポジトリへの書込スコープと `workflow`、
fine-grained PATでは対象forkへのContents/Workflowsの書込と、実行にはActionsの書込を確認する。

GitHubの `workflow_dispatch` はデフォルトブランチ上にもworkflowが必要。
2026-10-20に確認したforkの `main` には新しいworkflowファイルがまだない。
専用ブランチをpushしただけで `gh workflow run` が使えるとは限らない。
登録は別途レビューの上、**今回追加した4ファイルだけ**をforkの `main` に取り込む。
元検証ブランチ全体のmergeは他のNode/V8変更を巻き込むので行わない。
この登録操作も現段階では未承認・未実施。upstreamへのPRやIssueコメントは不要。

承認後、ローカル差分を確認して専用ブランチへcommit・pushする例:

```bash
cd /workspace/node
git diff --check
git diff --stat
git add .github/workflows/issue-66803-js-regression.yml tools/validation-66803-js/run.py tools/validation-66803-js/preflight.cjs tools/validation-66803-js/README.md
git diff --cached
# 人間の氏名・メールを設定し、人間自身がDCOを確認してsign-offする。
git commit -s -m "test: add artifact-based RISC-V JS regression workflow" -m "Assisted-by: Codex"
git push origin HEAD:validation/issue-66803-js-regression
```

forkのmainへの登録は、そのmainから作った別ブランチに上の専用commitだけをcherry-pickし、
人間のレビュー後に4ファイルだけを取り込む方法がある。
既存mainの変更や既存PR本文は編集しない。登録前にmain上の既存push workflowを確認し、
登録用commitメッセージに `[skip ci]` を付けてpushイベントのCIを抑止する。
この指定は後の `workflow_dispatch` を妨げない。フルビルドが起動しないことを確認できるまで、
また登録作業を含めた承認範囲が確定するまで、mainへpushしない。

登録後の初回実行:

```bash
gh workflow run issue-66803-js-regression.yml --repo inoway46/node --ref validation/issue-66803-js-regression -f scope=small
gh run list --repo inoway46/node --workflow issue-66803-js-regression.yml --branch validation/issue-66803-js-regression --event workflow_dispatch --limit 5
# 上の一覧で得たrun IDを指定する。
gh run watch RUN_ID --repo inoway46/node --exit-status
gh run download RUN_ID --repo inoway46/node --name issue-66803-js-small-RUN_ID-1 --dir results-small
```

再実行時のartifact名末尾は `run_attempt` に合わせる。
初回の結果を確認した後、同じdispatchの `-f scope=parallel` などで範囲を広げる。
pushだけではこの新workflowは起動しない。

## 結果の読み方

ActionsのSummaryと `summary.json` / `summary.md` を入口にする。
失敗をexit 0に変換しない。summary作成やartifact uploadが成功しても、先行stepの失敗は残る。

| 証跡 | 読み方 |
| --- | --- |
| `state.txt`, `*-error.txt` | prepare/preflight/testのどの段階で止まったか |
| `core.tap`, `temporal.tap` またはscope名の `.tap` | pass、not ok、runtime skip、失敗のstdout/stderrとtimeout診断 |
| 同名 `.stdout` | `--report` のstatus-rule skip数、探査・各テストの実行コマンド、所要時間 |
| 同名 `.stderr` | Pythonランナー自体のstderr。各失敗テストの捕捉stderrはTAP診断にも入る |
| `*.command.json`, `*.result.json` | argv、cwd、外側timeout、終了コード、実測時間、spawn error |
| `*-incomplete.txt` | TAP planなし・0件・未完走。ランナーが0終了でもworkflowは失敗にする |
| `selected-tests.json`, `status-rules/` | 選択候補と元のskip規則。status skipはTAP planの外側 |
| `target-environment.json`, `target-elf.*`, `host-versions.log` | QEMU設定、ELF、ホスト・QEMUバージョン |
| `direct-elf-spawn-fork-worker.stdout` | 対象Nodeのversions/config、事前検証結果 |
| `provenance.json`, `original-build/`, `restored-source-diff.stdout` | base、元workflow SHA、適用patch、manifest、ハッシュ |

`summary.json` のFailはランナーの期待値/status判定に基づくTAPの `not ok` 数。
既存の期待失敗条件も保存されたstatusと照合する。
ランナー全体のtimeoutと、個別テストのtimeoutを区別する。
キャンセルやrunner喪失時には `if: always()` でもartifact保存が完了しないことがある。

検証できるのは、保存したビルドと対応ソースの選択JSテストが、このQEMU・CPU設定で
どう動作するか。RISC-V実機、全Nodeテスト、cctest/addon群、全CI、
候補V8修正の正しさやIssue全体の解決は保証しない。

## この変更のローカル確認

実物artifactの展開とハッシュ照合、baseへの1回のpatch適用、復元差分のハッシュ一致、
15本の実在・元test.pyによる重複なしの選択・依存ソース確認、actionlint、
Python/JS構文検査、Pythonサブプロセスによる非0終了と外側timeoutの伝搬確認を実施。
対象RISC-V Nodeによるテスト、binfmt下の事前検証、GHAでの実行時間はまだ未検証。
ホストNodeの構文検査を対象Nodeのテスト結果として数えない。
