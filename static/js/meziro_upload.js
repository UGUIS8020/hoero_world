
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

    function displayFiles() {
        fileList.innerHTML = "";
        totalSize = 0;

        // ファイルパスでグループ化
        const filesByFolder = {};
        let totalFileCount = 0;

        selectedFiles.forEach((file) => {
            totalSize += file.size;
            totalFileCount++;
            const path = getRelativePath(file);
            const folderPath = path.includes("/")
                ? path.substring(0, path.lastIndexOf("/"))
                : "";

            if (!filesByFolder[folderPath]) {
                filesByFolder[folderPath] = [];
            }
            filesByFolder[folderPath].push(file);
        });

        // フォルダ数とファイル数の概要を表示
        const folderCount = Object.keys(filesByFolder).filter(f => f !== "").length;
        
        const summaryItem = document.createElement("div");
        summaryItem.className = "file-summary";
        
        let summaryText = `合計 ${totalFileCount} ファイル選択済み (${formatFileSize(totalSize)})`;
        if (folderCount > 0) {
            summaryText += `, ${folderCount} フォルダ`;
        }
        
        summaryItem.textContent = summaryText;
        fileList.appendChild(summaryItem);

        // オプション: フォルダごとの概要を簡易表示
        Object.keys(filesByFolder).sort().forEach((folder) => {
            const files = filesByFolder[folder];
            const folderSize = files.reduce((sum, file) => sum + file.size, 0);
            
            if (folder !== "") {
                const folderItem = document.createElement("div");
                folderItem.className = "folder-summary";
                folderItem.textContent = `📁 ${folder}/: ${files.length} ファイル (${formatFileSize(folderSize)})`;
                fileList.appendChild(folderItem);
            } else if (folder === "" && files.length > 0) {
                const rootItem = document.createElement("div");
                rootItem.className = "folder-summary";
                rootItem.textContent = `ルートディレクトリ: ${files.length} ファイル (${formatFileSize(folderSize)})`;
                fileList.appendChild(rootItem);
            }
        });

        if (selectedFiles.length > 0) {
            showStatus(
                `${selectedFiles.length}ファイル選択済み (合計: ${formatFileSize(totalSize)})`,
                "info"
            );
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
        if (files.length === 0) return;

        const formData = new FormData();

        // CSRFトークンを追加（最初に追加しておく）
        formData.append("csrf_token", csrf_token);

        const message = document.getElementById("userMessage").value;
        if (message) {
            formData.append("message", message);
        }

        let totalBytes = files.reduce((sum, file) => sum + file.size, 0);
        let uploadedBytes = 0;

        // ファイルパスを保持するためのディレクトリ構造
        const paths = {};

        for (const file of files) {
            const path = getRelativePath(file);
            formData.append("files[]", file);
            // パス情報を別途送信
            paths[file.name] = path;
        }

        // パス情報をJSONとして追加
        formData.append("paths", JSON.stringify(paths));

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
            dirReader.readEntries(async (entries) => {
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
            }, (error) => {
                console.error("ディレクトリの読み込みエラー:", error);
                resolve(files);
            });
        }
        
        readEntries();
    });
}

// FileEntryからFileオブジェクトを取得する関数
function getFileFromEntry(fileEntry) {
    return new Promise((resolve) => {
        fileEntry.file(
            (file) => resolve(file),
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
    const validFiles = files.filter(file => file !== null);
    
    if (validFiles.length > 0) {
        addFiles(validFiles);
        showStatus(`${validFiles.length}個のファイルが選択されました。`, "success");
    }
}

// ファイル選択処理
fileInput.addEventListener("change", (e) => {
    handleFiles(Array.from(e.target.files));
});

// フォルダ選択処理
folderInput.addEventListener("change", (e) => {
    handleFiles(Array.from(e.target.files));
});

// アップロードボタンクリック時
uploadButton.addEventListener("click", () => {
    const message = document.getElementById("userMessage").value.trim();

    // ここでメッセージが空かチェックしてアラート表示
    if (!message) {
        showStatus("⚠️ メッセージを入力してください。", "error");
        alert("メッセージが未入力です。入力してからアップロードしてください。");
        return; // 処理を中止
    }

    if (selectedFiles.length > 0) {
        uploadFiles(selectedFiles); // メッセージは uploadFiles 内で取得済みなのでそのままでOK
    }
});

// クリアボタンクリック時
clearButton.addEventListener("click", () => {
    selectedFiles = [];
    fileList.innerHTML = "";
    showStatus("ファイル選択をクリアしました。", "info");
    updateButtonState();
});