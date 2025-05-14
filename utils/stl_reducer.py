import os
import numpy as np
import trimesh

# STLファイルを縮小する関数
def reduce_stl_size(input_file, output_file, target_reduction=0.5, binary_output=True):
    """
    STLファイルのサイズを削減する関数
    
    Parameters:
    input_file (str): 入力STLファイルのパス
    output_file (str): 出力STLファイルのパス
    target_reduction (float): 目標削減率（0.5 = 50%削減）
    binary_output (bool): バイナリSTLとして出力するかどうか
    
    Returns:
    tuple: (元のファイルサイズ, 新しいファイルサイズ, 削減率)
    """
    # STLファイルを読み込む
    mesh = trimesh.load_mesh(input_file)
    
    # 元のファイルサイズを取得
    original_size = os.path.getsize(input_file)
    
    # 元の面の数
    original_faces = len(mesh.faces)
    
    # 目標とする面の数を計算
    target_faces = int(original_faces * (1 - target_reduction))
    
    # メッシュを簡略化
    mesh_simplified = mesh.simplify_quadratic_decimation(target_faces)
    
    # 出力フォーマットを設定（バイナリまたはアスキー）
    export_type = 'binary' if binary_output else 'ascii'
    
    # 簡略化したメッシュを保存
    mesh_simplified.export(output_file, file_type='stl', file_format=export_type)
    
    # 新しいファイルサイズを取得
    new_size = os.path.getsize(output_file)
    
    # 削減率を計算
    reduction = 1 - (new_size / original_size)
    
    result = {
        'original_size': original_size / 1024,  # KBに変換
        'new_size': new_size / 1024,  # KBに変換
        'reduction': reduction * 100,
        'original_faces': original_faces,
        'new_faces': len(mesh_simplified.faces)
    }
    
    return result