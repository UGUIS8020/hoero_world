// DentalChart コンポーネント
const DentalChart = () => {
    // 歯の初期状態（全て健全）を設定
    const initialTeethState = {
      upperRight: Array(8).fill(false),
      upperLeft: Array(8).fill(false),
      lowerRight: Array(8).fill(false),
      lowerLeft: Array(8).fill(false)
    };
  
    const [teethState, setTeethState] = React.useState(initialTeethState);
    const [missingCount, setMissingCount] = React.useState(0);
    const [combinations, setCombinations] = React.useState(0);
  
    // 歯を選択/選択解除する処理
    const toggleTooth = (jaw, side, index) => {
      setTeethState(prevState => {
        const newState = { ...prevState };
        newState[`${jaw}${side}`][index] = !newState[`${jaw}${side}`][index];
        return newState;
      });
    };
  
    // 二項係数（組み合わせ）を計算する関数
    const calculateCombination = (n, k) => {
      if (k < 0 || k > n) return 0;
      if (k === 0 || k === n) return 1;
      if (k > n / 2) k = n - k; // 効率化のため
      
      let result = 1;
      for (let i = 1; i <= k; i++) {
        result = result * (n - i + 1) / i;
      }
      return Math.round(result);
    };
  
    // 欠損歯数の更新と組み合わせ計算
    React.useEffect(() => {
      // 欠損歯数をカウント
      const count = Object.values(teethState).flat().filter(Boolean).length;
      setMissingCount(count);
      
      // 組み合わせ数を計算
      const combs = calculateCombination(28, count);
      setCombinations(combs);
    }, [teethState]);
  
    // すべての歯をリセット
    const resetAll = () => {
      setTeethState(initialTeethState);
    };
  
    // 数字の表示（8から1、1から8）
    const upperNumbers = [8, 7, 6, 5, 4, 3, 2, 1, 1, 2, 3, 4, 5, 6, 7, 8];
    const lowerNumbers = [8, 7, 6, 5, 4, 3, 2, 1, 1, 2, 3, 4, 5, 6, 7, 8];
  
    return (
        <div className="w-full max-w-4xl mx-auto p-4 bg-white rounded-lg shadow-md">
            <h1 className="text-2xl font-bold text-center mb-6 text-gray-800 pb-2 border-b-2 border-blue-500">
                歯牙欠損選択チャート（Dental Defect Selection Chart）
            </h1>

            <div className="mb-6 text-center">
                <p className="text-gray-700">
                    チェックを入れた歯は欠損歯としてカウントされます。
                </p>
                <p className="text-gray-700">
                    Check the boxes to mark teeth as missing.
                </p>
            </div>

            {/* 上顎歯番号表示 */}
            <div className="flex justify-center mb-1">
                <div className="text-center font-bold mb-1 text-gray-700">
                    Upper Right
                </div>
                <div className="flex-grow"></div>
                <div className="text-center font-bold mb-1 text-gray-700">
                    Upper Left
                </div>
            </div>

            <div className="flex justify-center mb-2">
                {upperNumbers.map((num, idx) => (
                    <div key={`upper-${idx}`} className="w-10 text-center">
                        <span className="text-sm font-semibold text-gray-600">
                            {num}
                        </span>
                    </div>
                ))}
            </div>

            {/* 上顎チェックボックス */}
            <div className="flex justify-center mb-6">
                {Array(8)
                    .fill(0)
                    .map((_, idx) => (
                        <div key={`ur-${idx}`} className="w-10 text-center">
                            <label className="inline-block w-8 h-8 rounded-full border-2 border-gray-300 cursor-pointer hover:bg-gray-100 flex items-center justify-center">
                                <input
                                    type="checkbox"
                                    className="sr-only"
                                    checked={teethState.upperRight[idx]}
                                    onChange={() =>
                                        toggleTooth("upper", "Right", idx)
                                    }
                                />
                                {teethState.upperRight[idx] && (
                                    <span className="block w-6 h-6 bg-red-200 rounded-full"></span>
                                )}
                            </label>
                        </div>
                    ))}
                {Array(8)
                    .fill(0)
                    .map((_, idx) => (
                        <div key={`ul-${idx}`} className="w-10 text-center">
                            <label className="inline-block w-8 h-8 rounded-full border-2 border-gray-300 cursor-pointer hover:bg-gray-100 flex items-center justify-center">
                                <input
                                    type="checkbox"
                                    className="sr-only"
                                    checked={teethState.upperLeft[idx]}
                                    onChange={() =>
                                        toggleTooth("upper", "Left", idx)
                                    }
                                />
                                {teethState.upperLeft[idx] && (
                                    <span className="block w-6 h-6 bg-red-200 rounded-full"></span>
                                )}
                            </label>
                        </div>
                    ))}
            </div>

            {/* 下顎チェックボックス */}
            <div className="flex justify-center mb-2">
                {Array(8)
                    .fill(0)
                    .map((_, idx) => (
                        <div key={`lr-${idx}`} className="w-10 text-center">
                            <label className="inline-block w-8 h-8 rounded-full border-2 border-gray-300 cursor-pointer hover:bg-gray-100 flex items-center justify-center">
                                <input
                                    type="checkbox"
                                    className="sr-only"
                                    checked={teethState.lowerRight[idx]}
                                    onChange={() =>
                                        toggleTooth("lower", "Right", idx)
                                    }
                                />
                                {teethState.lowerRight[idx] && (
                                    <span className="block w-6 h-6 bg-red-200 rounded-full"></span>
                                )}
                            </label>
                        </div>
                    ))}
                {Array(8)
                    .fill(0)
                    .map((_, idx) => (
                        <div key={`ll-${idx}`} className="w-10 text-center">
                            <label className="inline-block w-8 h-8 rounded-full border-2 border-gray-300 cursor-pointer hover:bg-gray-100 flex items-center justify-center">
                                <input
                                    type="checkbox"
                                    className="sr-only"
                                    checked={teethState.lowerLeft[idx]}
                                    onChange={() =>
                                        toggleTooth("lower", "Left", idx)
                                    }
                                />
                                {teethState.lowerLeft[idx] && (
                                    <span className="block w-6 h-6 bg-red-200 rounded-full"></span>
                                )}
                            </label>
                        </div>
                    ))}
            </div>

            {/* 下顎歯番号表示 */}
            <div className="flex justify-center mb-4">
                {lowerNumbers.map((num, idx) => (
                    <div key={`lower-${idx}`} className="w-10 text-center">
                        <span className="text-sm font-semibold text-gray-600">
                            {num}
                        </span>
                    </div>
                ))}
            </div>

            <div className="flex justify-center mb-6">
                <div className="text-center font-bold mb-1 text-gray-700">
                    Lower Right
                </div>
                <div className="flex-grow"></div>
                <div className="text-center font-bold mb-1 text-gray-700">
                    Lower Left
                </div>{" "}
            </div>

            {/* 欠損歯数と組み合わせ表示 */}
            <div className="mt-8 p-6 bg-blue-50 rounded-lg border border-blue-200">
                <div className="text-center mb-4">
                    <button
                        onClick={resetAll}
                        className="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded"
                    >
                        リセット (Reset)
                    </button>
                </div>

                <div className="text-center text-lg font-bold mb-2">
                    <span className="mr-2">欠損歯数:</span>
                    <span className="text-2xl text-red-600">
                        {missingCount}
                    </span>
                    <span className="ml-2">本</span>
                </div>

                <div className="text-center text-lg font-bold">
                    <span className="mr-2">
                        {missingCount}歯欠損の可能な組み合わせ数:
                    </span>
                    <span className="text-2xl text-blue-600">
                        {combinations.toLocaleString("ja-JP")}
                    </span>
                    <span className="ml-2">通り</span>
                </div>

                <div className="mt-4 text-center text-gray-600">
                    <p>
                        選択した歯の欠損パターンは、28本中の{missingCount}
                        本欠損パターンの1つです。
                    </p>
                    <p>
                        The selected pattern is one of{" "}
                        {combinations.toLocaleString("en-US")} possible
                        combinations for {missingCount} missing teeth out of 28.
                    </p>
                </div>
            </div>
        </div>
    );
  };
  
  // コンポーネントをエクスポート（FlaskのHTMLテンプレートから参照するため）