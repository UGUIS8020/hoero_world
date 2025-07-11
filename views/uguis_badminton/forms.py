from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, DateField
from wtforms.validators import DataRequired, Email, ValidationError, Length, Optional, EqualTo
from flask import current_app
from flask_login import UserMixin


class LoginForm(FlaskForm):
    email = StringField('メールアドレス', validators=[DataRequired(message='メールアドレスを入力してください'), Email(message='正しいメールアドレスの形式で入力してください')])
    password = PasswordField('パスワード', validators=[DataRequired(message='パスワードを入力してください')])
    remember = BooleanField('ログイン状態を保持する')    
    submit = SubmitField('ログイン')

    def __init__(self, *args, **kwargs):
        super(LoginForm, self).__init__(*args, **kwargs)
        self.user = None  # self.userを初期化

    def validate_email(self, field):
        """メールアドレスの存在確認"""
        try:
            # メールアドレスでユーザーを検索
            response = current_app.table.query(
                IndexName='email-index',
                KeyConditionExpression='email = :email',
                ExpressionAttributeValues={
                    ':email': field.data
                }
            )
            
            items = response.get('Items', [])
            if not items:
                raise ValidationError('このメールアドレスは登録されていません')            
            
            # ユーザー情報を保存（パスワード検証で使用）
            self.user = items[0]
            # ユーザーをロード
            current_app.logger.debug(f"User found for email: {field.data}")       
           
        
        except Exception as e:
            current_app.logger.error(f"Login error: {e}")
            raise ValidationError('ログイン処理中にエラーが発生しました')
        
class UpdateUserForm(FlaskForm):
    organization = SelectField('所属', choices=[('鶯', '鶯'), ('gest', 'ゲスト'), ('Boot_Camp15', 'Boot Camp15'), ('other', 'その他')], default='鶯', validators=[DataRequired(message='所属を選択してください')])
    display_name = StringField('表示名 LINE名など', validators=[DataRequired(), Length(min=1, max=30)])
    user_name = StringField('ユーザー名', validators=[DataRequired()])
    furigana = StringField('フリガナ', validators=[Optional()])
    phone = StringField('電話番号', validators=[Optional(), Length(min=10, max=15)])
    post_code = StringField('郵便番号', validators=[Optional(), Length(min=7, max=7)])
    address = StringField('住所', validators=[Optional(), Length(max=100)])    
    email = StringField('メールアドレス', validators=[DataRequired(), Email()])
    email_confirm = StringField('確認用メールアドレス', validators=[Optional(), Email()])
    password = PasswordField('パスワード', validators=[Optional(), Length(min=8), EqualTo('pass_confirm', message='パスワードが一致していません')])
    pass_confirm = PasswordField('パスワード(確認)')
    gender = SelectField('性別', choices=[('male', '男性'), ('female', '女性')], validators=[Optional()])
    date_of_birth = DateField('生年月日', format='%Y-%m-%d', validators=[Optional()])
    guardian_name = StringField('保護者氏名', validators=[Optional()])    
    emergency_phone = StringField('緊急連絡先電話番号', validators=[Optional(), Length(min=10, max=15, message='正しい電話番号を入力してください')])
    badminton_experience = SelectField(
        'バドミントン歴', 
        choices=[
            ('', 'バドミントン歴を選択してください'),
            ('未経験', '未経験'),
            ('1年未満', '1年未満'),
            ('1～3年未満', '1～3年未満'),
            ('3年以上', '3年以上')
        ], 
        validators=[
            DataRequired(message='バドミントン歴を選択してください')
        ]
    )

    submit = SubmitField('更新')

    def __init__(self, user_id, dynamodb_table, *args, **kwargs):
        super(UpdateUserForm, self).__init__(*args, **kwargs)
        self.id = f'user#{user_id}'
        self.table = dynamodb_table

         # フィールドを初期化
        self.email_readonly = True  # デフォルトでは編集不可

    def validate_email_confirm(self, field):
        # フォームでemailが変更されていない場合は何もしない
        if self.email_readonly:
            return

        # email_confirmが空の場合のエラーチェック
        if not field.data:
            raise ValidationError('確認用メールアドレスを入力してください。')

        # email_confirmが入力されている場合のみ一致を確認
        if field.data != self.email.data:
            raise ValidationError('メールアドレスが一致していません。再度入力してください。')
            

    def validate_email(self, field):
        # メールアドレスが変更されていない場合はバリデーションをスキップ
        if self.email_readonly or not field.data:
            return

        try:
            # DynamoDBにクエリを投げて重複チェックを実行
            response = self.table.query(
                IndexName='email-index',
                KeyConditionExpression='email = :email',
                ExpressionAttributeValues={
                    ':email': field.data
                }
            )

            current_app.logger.debug(f"Query response: {response}")

            if response.get('Items'):
                for item in response['Items']:
                    user_id = item.get('user#user_id') or item.get('user_id')
                    if user_id and user_id != self.id:
                        raise ValidationError('このメールアドレスは既に使用されています。他のメールアドレスをお試しください。')
        except ClientError as e:
            current_app.logger.error(f"Error querying DynamoDB: {e}")
            raise ValidationError('メールアドレスの確認中にエラーが発生しました。管理者にお問い合わせください。')
        except Exception as e:
            current_app.logger.error(f"Unexpected error querying DynamoDB: {e}")
            raise ValidationError('予期しないエラーが発生しました。管理者にお問い合わせください。')
        
class TempRegistrationForm(FlaskForm):
    # 表示名
    display_name = StringField(
        '表示名', 
        validators=[
            DataRequired(message='表示名を入力してください'),
            Length(min=1, max=30, message='表示名は1文字以上30文字以下で入力してください')
        ]
    )

    # 名前
    user_name = StringField(
        '名前',
        validators=[
            DataRequired(message='名前を入力してください'),
            Length(min=1, max=30, message='名前は1文字以上30文字以下で入力してください')
        ]
    )
    
    # 性別
    gender = SelectField(
        '性別', 
        choices=[
            ('', '性別を選択してください'),
            ('male', '男性'),
            ('female', '女性')
        ], 
        validators=[
            DataRequired(message='性別を選択してください')
        ]
    )
    
    # バドミントン歴
    badminton_experience = SelectField(
        'バドミントン歴', 
        choices=[
            ('', 'バドミントン歴を選択してください'),
            ('未経験', '未経験'),
            ('1年未満', '1年未満'),
            ('1～3年未満', '1～3年未満'),
            ('3年以上', '3年以上')
        ], 
        validators=[
            DataRequired(message='バドミントン歴を選択してください')
        ]
    )
    
    # メールアドレス
    email = StringField(
        'メールアドレス', 
        validators=[
            DataRequired(message='メールアドレスを入力してください'),
            Email(message='正しいメールアドレスを入力してください')
        ]
    )
    
    # パスワード
    password = PasswordField(
        'パスワード', 
        validators=[
            DataRequired(message='パスワードを入力してください'),
            Length(min=8, message='パスワードは8文字以上で入力してください')
        ]
    )
    
    # 登録ボタン
    submit = SubmitField('仮登録')  

class User(UserMixin):
    def __init__(self, user_id, display_name, user_name, furigana, email, password_hash,
                 gender, date_of_birth, post_code, address, phone, guardian_name, emergency_phone, badminton_experience,
                 organization='other', administrator=False, 
                 created_at=None, updated_at=None):
        super().__init__()
        self.id = user_id
        self.display_name = display_name
        self.user_name = user_name
        self.furigana = furigana
        self.email = email 
        self._password_hash = password_hash
        self.gender = gender
        self.date_of_birth = date_of_birth
        self.post_code = post_code
        self.address = address
        self.phone = phone
        self.guardian_name = guardian_name 
        self.emergency_phone = emergency_phone 
        self.organization = organization
        self.badminton_experience = badminton_experience
        self.administrator = administrator
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def check_password(self, password):
        return check_password_hash(self._password_hash, password)  # _password_hashを使用

    @property
    def is_admin(self):
        return self.administrator    
   

    @staticmethod
    def from_dynamodb_item(item):
        def get_value(field, default=None):
            return item.get(field, default)

        return User(
            user_id=get_value('user#user_id'),
            display_name=get_value('display_name'),
            user_name=get_value('user_name'),
            furigana=get_value('furigana'),
            email=get_value('email'),
            password_hash=get_value('password'),  # 修正：password フィールドを取得
            gender=get_value('gender'),
            date_of_birth=get_value('date_of_birth'),
            post_code=get_value('post_code'),
            address=get_value('address'),
            phone=get_value('phone'),
            guardian_name=get_value('guardian_name', default=None),
            emergency_phone=get_value('emergency_phone', default=None),
            organization=get_value('organization', default='other'),
            badminton_experience=get_value('badminton_experience'),
            administrator=bool(get_value('administrator', False)),
            created_at=get_value('created_at'),
            updated_at=get_value('updated_at')
        )

    def to_dynamodb_item(self):
        fields = ['user_id', 'organization', 'address', 'administrator', 'created_at', 
                  'display_name', 'email', 'furigana', 'gender', 'password', 
                  'phone', 'post_code', 'updated_at', 'user_name','guardian_name', 'emergency_phone']
        item = {field: {"S": str(getattr(self, field))} for field in fields if getattr(self, field, None)}
        item['administrator'] = {"BOOL": self.administrator}
        if self.date_of_birth:
            item['date_of_birth'] = {"S": str(self.date_of_birth)}
        
        return item