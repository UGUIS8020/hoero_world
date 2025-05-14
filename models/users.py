from flask_wtf import FlaskForm
from wtforms import ValidationError, StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo
from models.common import User

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('ログイン')

class RegistrationForm(FlaskForm):
    email = StringField('メールアドレス', validators=[DataRequired(), Email(message='正しいメールアドレスを入力してください')])
    # usernameをdisplay_nameに変更
    display_name = StringField('ユーザー名', validators=[DataRequired()])
    # 他のフィールドも追加
    sender_name = StringField('送信者名（医院名・技工所名）')
    full_name = StringField('氏名')
    phone = StringField('電話番号')
    postal_code = StringField('郵便番号')
    prefecture = StringField('都道府県')
    address = StringField('住所')
    building = StringField('建物名・部屋番号')
    
    password = PasswordField('パスワード', validators=[DataRequired(), EqualTo('pass_confirm', message='パスワードが一致していません')])
    pass_confirm = PasswordField('パスワード(確認)', validators=[DataRequired()])
    submit = SubmitField('登録')

    def validate_display_name(self, field):
        # usernameをdisplay_nameに変更
        if User.query.filter_by(display_name=field.data).first():
            raise ValidationError('入力されたユーザー名は既に使われています。')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('入力されたメールアドレスは既に登録されています。') 

class UpdateUserForm(FlaskForm):
    display_name = StringField('ユーザー名', validators=[DataRequired()])
    email = StringField('メールアドレス', validators=[DataRequired(), Email()])
    full_name = StringField('氏名')
    sender_name = StringField('送信者名（医院名・技工所名）')
    phone = StringField('電話番号')
    postal_code = StringField('郵便番号')
    prefecture = StringField('都道府県')
    address = StringField('住所')
    building = StringField('建物名・部屋番号')
    password = PasswordField('新パスワード', validators=[])
    pass_confirm = PasswordField('新パスワード(確認)', validators=[EqualTo('password', message='パスワードが一致していません')])
    submit = SubmitField('更新')

    def __init__(self, user_id, *args, **kwargs):
        super(UpdateUserForm, self).__init__(*args, **kwargs)
        self.id = user_id

    def validate_email(self, field):
        if User.query.filter(User.id != self.id).filter_by(email=field.data).first():
            raise ValidationError('入力されたメールアドレスは既に登録されています。')

    def validate_display_name(self, field):
        if User.query.filter(User.id != self.id).filter_by(display_name=field.data).first():
            raise ValidationError('入力されたユーザー名は既に使われています。')
