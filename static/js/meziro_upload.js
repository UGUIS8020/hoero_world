const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const folderInput = document.getElementById("folderInput");
const fileList = document.getElementById("fileList");
const status = document.getElementById("status");
const uploadButton = document.getElementById("uploadButton");
const clearButton = document.getElementById("clearButton");
const progressContainer = document.getElementById("progressContainer");
const progressBar = document.getElementById("progressBar");

let selectedFiles = []; // 選択されたファイルを保持
let totalSize = 0;

// 100件以上のファイルを取得するために必要な関数
async function readAllEntries(reader) {
    const entries = [];

    async function readBatch() {
        return new Promise((resolve, reject) => {
            reader.readEntries((batch) => {
                if (batch.length === 0) {
                    resolve(null); // 終了条件
                } else {
                    resolve(batch);
                }
            }, reject);
        });
    }

    let batch;
    while ((batch = await readBatch()) !== null) {
        entries.push(...batch);
    }

    return entries;
}

function showStatus(message, type) {
    status.innerHTML = `<div class="${type}">${message}</div>`;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    if (bytes < 1024 * 1024 * 1024)
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    return (bytes / (1024 * 1024 * 1024)).toFixed(1) + " GB";
}

function updateButtonState() {
    uploadButton.disabled = selectedFiles.length === 0;
    clearButton.disabled = selectedFiles.length === 0;
}

function getRelativePath(file) {
    // webkitRelativePath がある場合はそれを使用
    if (file.webkitRelativePath) return file.webkitRelativePath;

    // DataTransferItemでのフォルダアップロードの場合
    if (file.relativePath) return file.relativePath;

    // 通常のファイル
    return file.name;
}

function isFolderEntry(entry) {
    return entry && entry.isDirectory;
}

// function displayFiles() {
//     fileList.innerHTML = "";
//     totalSize = 0;

//     // ファイルパスでグループ化
//     const filesByFolder = {};
//     let totalFileCount = 0;

//     selectedFiles.forEach((file) => {
//         totalSize += file.size;
//         totalFileCount++;
//         const path = getRelativePath(file);
//         const folderPath = path.includes("/")
//             ? path.substring(0, path.lastIndexOf("/"))
//             : "";

//         if (!filesByFolder[folderPath]) {
//             filesByFolder[folderPath] = [];
//         }
//         filesByFolder[folderPath].push(file);
//     });

//     // フォルダごとのファイル一覧を表示
//     Object.keys(filesByFolder)
//         .sort()
//         .forEach((folder) => {
//             const files = filesByFolder[folder];
//             const folderSize = files.reduce((sum, file) => sum + file.size, 0);

//             if (folder !== "") {
//                 // フォルダ名のみ表示
//                 const folderItem = document.createElement("div");
//                 folderItem.className = "folder-summary";
//                 folderItem.textContent = `📁 ${folder}/ (${
//                     files.length
//                 } ファイル, ${formatFileSize(folderSize)})`;
//                 fileList.appendChild(folderItem);
//             } else {
//                 // フォルダに属さないファイルはそのまま表示
//                 files.forEach((file) => {
//                     const fileItem = document.createElement("div");
//                     fileItem.className = "file-item";
//                     fileItem.textContent = `📄 ${file.name} (${formatFileSize(
//                         file.size
//                     )})`;
//                     fileList.appendChild(fileItem);
//                 });
//             }
//         });
// }

function displayFiles() {
    fileList.innerHTML = "";
    totalSize = 0;

    // ファイルパスでグループ化
    const filesByFolder = {};
    let totalFileCount = 0;

    // デバッグ用にパス情報を確認
    console.log("選択されたファイル:");

    selectedFiles.forEach((file) => {
        totalSize += file.size;
        totalFileCount++;
        const path = getRelativePath(file);
        console.log(`- ${file.name}: パス=${path}`); // デバッグ出力

        const folderPath = path.includes("/")
            ? path.substring(0, path.lastIndexOf("/"))
            : "";

        if (!filesByFolder[folderPath]) {
            filesByFolder[folderPath] = [];
        }
        filesByFolder[folderPath].push(file);
    });

    // デバッグ用にフォルダ構造を確認
    console.log("フォルダ構造:", Object.keys(filesByFolder));

    // 合計情報の表示
    const folderCount = Object.keys(filesByFolder).filter(
        (f) => f !== ""
    ).length;
    const summaryItem = document.createElement("div");
    summaryItem.className = "file-summary";
    let summaryText = `合計 ${totalFileCount} ファイル選択済み (${formatFileSize(
        totalSize
    )})`;
    if (folderCount > 0) {
        summaryText += `, ${folderCount} フォルダ`;
    }
    summaryItem.textContent = summaryText;
    fileList.appendChild(summaryItem);

    // フォルダとファイルを分けて表示
    // 1. まずフォルダのみ表示
    Object.keys(filesByFolder)
        .sort()
        .filter((folder) => folder !== "") // フォルダのみフィルタリング
        .forEach((folder) => {
            const files = filesByFolder[folder];
            const folderSize = files.reduce((sum, file) => sum + file.size, 0);

            // フォルダコンテナを作成
            const folderContainer = document.createElement("div");
            folderContainer.className = "folder-container";
            fileList.appendChild(folderContainer);

            // フォルダ名表示
            const folderItem = document.createElement("div");
            folderItem.className = "folder-summary clickable";
            folderItem.textContent = `📁 ${folder}/ (${
                files.length
            } ファイル, ${formatFileSize(folderSize)})`;
            folderContainer.appendChild(folderItem);

            // ファイルリストコンテナ（初期状態は非表示）
            const filesContainer = document.createElement("div");
            filesContainer.className = "files-container";
            filesContainer.style.display = "none"; // 非表示
            folderContainer.appendChild(filesContainer);

            // フォルダ内のファイル一覧をコンテナに追加
            files.forEach((file) => {
                const fileItem = document.createElement("div");
                fileItem.className = "file-item";
                fileItem.textContent = `・${file.name} (${formatFileSize(
                    file.size
                )})`;
                filesContainer.appendChild(fileItem);
            });

            // クリックイベントでファイル一覧の表示/非表示を切り替え
            folderItem.addEventListener("click", function () {
                if (filesContainer.style.display === "none") {
                    filesContainer.style.display = "block";
                } else {
                    filesContainer.style.display = "none";
                }
            });
        });

    // 2. ルート直下のファイルを表示
    if (filesByFolder[""] && filesByFolder[""].length > 0) {
        const rootFiles = filesByFolder[""];
        const rootSize = rootFiles.reduce((sum, file) => sum + file.size, 0);

        // ルートファイルのヘッダー
        const rootHeader = document.createElement("div");
        rootHeader.className = "folder-summary";
        rootHeader.textContent = `ルートファイル (${
            rootFiles.length
        } ファイル, ${formatFileSize(rootSize)})`;
        fileList.appendChild(rootHeader);

        // ルートファイル一覧
        rootFiles.forEach((file) => {
            const fileItem = document.createElement("div");
            fileItem.className = "file-item";
            fileItem.textContent = `📄 ${file.name} (${formatFileSize(
                file.size
            )})`;
            fileList.appendChild(fileItem);
        });
    }
}

// ファイル追加処理
function addFiles(files) {
    // サイズチェック
    const oversizedFiles = Array.from(files).filter(
        (f) => f.size > 2 * 1024 * 1024 * 1024
    );
    if (oversizedFiles.length > 0) {
        showStatus(
            `警告: 次のファイルは2GBを超えるため無視されました: ${oversizedFiles
                .map((f) => f.name)
                .join(", ")}`,
            "error"
        );
    }

    // 有効なファイルだけを追加
    const validFiles = Array.from(files).filter(
        (f) => f.size <= 2 * 1024 * 1024 * 1024
    );

    // 重複チェック
    for (const file of validFiles) {
        const path = getRelativePath(file);
        const duplicate = selectedFiles.find(
            (f) => getRelativePath(f) === path
        );

        if (!duplicate) {
            selectedFiles.push(file);
        }
    }

    displayFiles();
    updateButtonState();
}

// フォルダからファイルを再帰的に読み込む
async function readEntryRecursively(entry) {
    if (isFolderEntry(entry)) {
        const reader = entry.createReader();
        const entries = await readAllEntries(reader); // ✅ ここを変更

        for (const childEntry of entries) {
            await readEntryRecursively(childEntry);
        }
    } else if (entry.isFile) {
        const file = await new Promise((resolve) => {
            entry.file(resolve);
        });

        file.relativePath = entry.fullPath.substring(1); // 先頭の '/' を除く
        const isDuplicate = selectedFiles.some(
            (f) => f.relativePath === file.relativePath
        );
        if (!isDuplicate && file.size <= 2 * 1024 * 1024 * 1024) {
            selectedFiles.push(file);
        }
    }
}

// ドラッグ＆ドロップされたアイテムを処理
async function uploadFiles(files) {
    const isPrescriptionPage = !!document.getElementById("PatientNameKana");
    if (files.length === 0 && !isPrescriptionPage) return;

    const formData = new FormData();

    // CSRFトークンを追加（最初に追加しておく）
    formData.append("csrf_token", csrf_token);

    // テキスト系入力を収集
    const businessName = document.getElementById("businessName").value;
    const userName = document.getElementById("userName").value;
    const userEmail = document.getElementById("userEmail").value;
    const patientName = document.getElementById("PatientName").value;
    const patientNameKana = document.getElementById("PatientNameKana") ? document.getElementById("PatientNameKana").value : "";
    const appointmentDate = document.getElementById("appointmentDate").value;
    const appointmentHour = document.getElementById("appointmentHour").value;
    const projectType = document.getElementById("projectType").value;
    const shade = document.getElementById("shade").value;
    const userMessage = document.getElementById("userMessage").value;

    // crown_type（ラジオボタン）
    const crownRadio = document.querySelector(
        'input[name="crown_type"]:checked'
    );
    const crownType = crownRadio ? crownRadio.value : "";

    // teeth[]（チェックボックス）
    const selectedTeeth = [];
    document.querySelectorAll('input[name="teeth[]"]:checked').forEach((cb) => {
        selectedTeeth.push(cb.value);
    });

    // ▼ 必須フィールドのバリデーション
    if (
        !businessName ||
        !userName ||
        !userEmail ||
        !patientName ||
        !appointmentDate ||
        !appointmentHour ||
        !projectType
    ) {
        showStatus("すべての必須項目を入力してください。", "error");
        return;
    }

    // ▼ FormData に追加
    formData.append("businessName", businessName);
    formData.append("userName", userName);
    formData.append("userEmail", userEmail);
    formData.append("PatientName", patientName);
    formData.append("PatientNameKana", patientNameKana);
    formData.append("appointmentDate", appointmentDate);
    formData.append("appointmentHour", appointmentHour);
    formData.append("projectType", projectType);
    formData.append("shade", shade);
    formData.append("userMessage", userMessage);
    formData.append("crown_type", crownType);
    formData.append("teeth", JSON.stringify(selectedTeeth)); // JSON文字列として送信

    // ▼ ファイル処理
    let totalBytes = files.reduce((sum, file) => sum + file.size, 0);
    let uploadedBytes = 0;

    const paths = {};

    if (files.length > 0) {
        for (const file of files) {
            const path = getRelativePath(file);
            formData.append("files[]", file);
            paths[file.name] = path;
        }
    }

    // パス情報をJSONとして追加
    formData.append("paths", JSON.stringify(paths));

    // フォルダ構造の有無を判定
    const hasFolder = Object.values(paths).some((path) => path.includes("/"));
    formData.append("has_folder_structure", hasFolder.toString());
    console.log("フォルダ構造の有無:", hasFolder); // デバッグ用

    progressContainer.style.display = "block";
    showStatus("ファイルをアップロード中...", "processing");
    uploadButton.disabled = true;
    clearButton.disabled = true;

    try {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/meziro_upload", true);

        // CSRFトークンをヘッダーに追加（これが重要な変更点）
        xhr.setRequestHeader("X-CSRFToken", csrf_token);

        // プログレス処理
        xhr.upload.onprogress = function (event) {
            if (event.lengthComputable) {
                uploadedBytes = event.loaded;
                const percentage = Math.round(
                    (uploadedBytes / totalBytes) * 100
                );
                progressBar.style.width = percentage + "%";
                progressBar.textContent = percentage + "%";
            }
        };

        xhr.onload = function () {
            if (xhr.status === 200) {
                const result = JSON.parse(xhr.responseText);
                showStatus(result.message || "アップロード成功", "success");
                fileList.innerHTML = "";
                selectedFiles = [];
                updateButtonState();
                progressContainer.style.display = "none";
                document.getElementById("userMessage").value = "";
            } else {
                // 修正：throw ではなく直接処理
                console.error("HTTPエラー:", xhr.status, xhr.statusText);
                showStatus(
                    "エラーが発生しました: " +
                        (xhr.statusText || "アップロードに失敗しました"),
                    "error"
                );
                progressContainer.style.display = "none";
                updateButtonState();
            }
        };

        xhr.onerror = function () {
            // 修正：throw ではなく直接処理
            console.error("ネットワークエラーが発生しました");
            showStatus("ネットワークエラーが発生しました", "error");
            progressContainer.style.display = "none";
            updateButtonState();
        };

        xhr.send(formData);
    } catch (error) {
        console.error("アップロードエラー:", error);
        showStatus("エラーが発生しました: " + error.message, "error");
        progressContainer.style.display = "none";
        updateButtonState();
    }
}

// ドラッグ＆ドロップ処理
dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("active");
});

dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("active");
});

dropZone.addEventListener("drop", async (e) => {
    e.preventDefault();
    dropZone.classList.remove("active");

    if (e.dataTransfer.items) {
        // DataTransferItemListを使用（フォルダとファイルの両方をサポート）
        await handleDroppedItems(e.dataTransfer.items);
    } else {
        // 従来のファイルリストを使用（フォルダ非サポート）
        handleFiles(Array.from(e.dataTransfer.files));
    }
});

// DataTransferItemListからファイルとフォルダを処理する関数
async function handleDroppedItems(items) {
    const filePromises = [];

    for (let i = 0; i < items.length; i++) {
        const item = items[i];

        if (item.kind === "file") {
            // webkitGetAsEntryがサポートされている場合はそれを使用
            if (item.webkitGetAsEntry) {
                const entry = item.webkitGetAsEntry();
                if (entry) {
                    if (entry.isDirectory) {
                        // フォルダの場合、再帰的に処理
                        filePromises.push(readDirectory(entry));
                    } else {
                        // ファイルの場合、そのまま追加
                        filePromises.push(Promise.resolve([item.getAsFile()]));
                    }
                }
            } else {
                // webkitGetAsEntryがサポートされていない場合は直接ファイルを取得
                filePromises.push(Promise.resolve([item.getAsFile()]));
            }
        }
    }

    // すべてのファイル取得が完了するのを待つ
    const fileArrays = await Promise.all(filePromises);
    // 平坦化して単一のファイル配列にする
    const allFiles = fileArrays.flat();

    // 取得したファイルをaddFilesに渡す
    handleFiles(allFiles);
}

// ディレクトリを再帰的に読み込む関数
function readDirectory(directoryEntry) {
    return new Promise((resolve) => {
        const dirReader = directoryEntry.createReader();
        const files = [];

        // ディレクトリ内のエントリを読み込む
        function readEntries() {
            dirReader.readEntries(
                async (entries) => {
                    if (entries.length === 0) {
                        // すべてのエントリを読み込んだらresolveする
                        resolve(files);
                        return;
                    }

                    // 各エントリを処理
                    for (let i = 0; i < entries.length; i++) {
                        const entry = entries[i];

                        if (entry.isDirectory) {
                            // サブディレクトリの場合、再帰的に読み込む
                            const subFiles = await readDirectory(entry);
                            files.push(...subFiles);
                        } else {
                            // ファイルの場合、Fileオブジェクトに変換して追加
                            files.push(await getFileFromEntry(entry));
                        }
                    }

                    // まだエントリが残っている可能性があるので再度読み込み
                    readEntries();
                },
                (error) => {
                    console.error("ディレクトリの読み込みエラー:", error);
                    resolve(files);
                }
            );
        }

        readEntries();
    });
}

// FileEntryからFileオブジェクトを取得する関数
function getFileFromEntry(fileEntry) {
    return new Promise((resolve) => {
        fileEntry.file(
            (file) => {
                // ここが重要: ファイルオブジェクトにパス情報を追加
                file.relativePath = fileEntry.fullPath.substring(1); // 先頭の '/' を除去
                resolve(file);
            },
            (error) => {
                console.error("ファイルの取得エラー:", error);
                resolve(null);
            }
        );
    });
}

// 複数ファイルを処理する関数
function handleFiles(files) {
    // nullを除外
    const validFiles = files.filter((file) => file !== null);

    if (validFiles.length > 0) {
        addFiles(validFiles);
        showStatus(
            `${validFiles.length}個のファイルが選択されました。`,
            "success"
        );
    }
}

// ファイル選択処理
fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
        // webkitGetAsEntry はドラッグ＆ドロップ専用なので、こちらは従来通り
        handleFiles(Array.from(e.target.files));
        showStatus(
            `${e.target.files.length}個のファイルが選択されました。`,
            "success"
        );
    }
});

// フォルダ選択処理
folderInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
        // ファイルが選択された場合、webkitRelativePathを持っているはず
        const hasWebkitRelativePath = Array.from(e.target.files).some(
            (file) => file.webkitRelativePath
        );

        console.log(
            "フォルダ選択されたファイル:",
            Array.from(e.target.files).map((f) => ({
                name: f.name,
                path: f.webkitRelativePath,
            }))
        );

        handleFiles(Array.from(e.target.files));
        showStatus(
            `${e.target.files.length}個のファイルが選択されました。${
                hasWebkitRelativePath ? "（フォルダ構造あり）" : ""
            }`,
            "success"
        );
    }
});
// クリアボタンクリック時
clearButton.addEventListener("click", () => {
    selectedFiles = [];
    fileList.innerHTML = "";
    showStatus("ファイル選択をクリアしました。", "info");
    updateButtonState();
});

// 部位選択用のチェックボックスのスタイル変更
document.addEventListener("DOMContentLoaded", function () {
    const teethCheckboxes = document.querySelectorAll('input[name="teeth[]"]');
    teethCheckboxes.forEach(function (checkbox) {
        checkbox.addEventListener("change", function () {
            const cell = this.parentElement;
            if (this.checked) {
                cell.style.outline = "2px solid #dc143c";
            } else {
                cell.style.outline = "none";
            }
        });
    });
});

document.addEventListener("DOMContentLoaded", function () {
    // 日付フィールドを選択
    const appointmentDateField = document.getElementById("appointmentDate");

    // 日付フィールドがクリックされたときにカレンダーを開く
    appointmentDateField.addEventListener("click", function () {
        if (typeof this.showPicker === "function") {
            this.showPicker();
        } else {
            this.blur();
            setTimeout(() => {
                this.focus();
            }, 10);
        }
    });
});

document.addEventListener("DOMContentLoaded", function () {
    const emailInput = document.getElementById("userEmail");

    emailInput.addEventListener("input", function () {
        // 全角英数字・記号を半角に置換
        this.value = this.value.replace(
            /[Ａ-Ｚａ-ｚ０-９！-～]/g,
            function (s) {
                return String.fromCharCode(s.charCodeAt(0) - 0xfee0);
            }
        );
    });
});

document.getElementById("uploadButton").addEventListener("click", function () {
    const requiredFields = [
        "businessName",
        "userName",
        "userEmail",
        "PatientName",
        "appointmentDate",
        "appointmentHour",
        "projectType",
    ];

    let hasError = false;

    // すべての入力欄をリセット（赤枠を消す）
    requiredFields.forEach((id) => {
        const element = document.getElementById(id);
        if (element) {
            element.classList.remove("input-error");
        }
    });

    // 未入力のものを赤くする
    requiredFields.forEach((id) => {
        const element = document.getElementById(id);
        if (element && !element.value.trim()) {
            element.classList.add("input-error");
            hasError = true;
        }
    });

    if (hasError) {
        const status = document.getElementById("status");
        status.innerHTML = `<div class="error">未入力の項目があります。すべて入力してください。</div>`;
        window.scrollTo({ top: status.offsetTop - 100, behavior: "smooth" });
        return;
    }

    // バリデーション通過後、アップロード処理へ進む（例）
    uploadFiles(selectedFiles); // ← ここは既存の送信関数に合わせて変更
});
