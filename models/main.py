from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, ValidationError, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email
from models.common import BlogCategory, BlogPost, Inquiry
from flask_wtf.file import FileField, FileAllowed


class BlogCategoryForm(FlaskForm):
    category = StringField('カテゴリ名', validators=[DataRequired()])
    submit = SubmitField('保存')

    def validate_category(self, field):
        if BlogCategory.query.filter_by(category=field.data).first():
            raise ValidationError('入力されたカテゴリ名は既に使われています。')

class UpdateCategoryForm(FlaskForm):
    category = StringField('カテゴリ名', validators=[DataRequired()])
    submit = SubmitField('更新')

    def __init__(self, blog_category_id, *args, **kwargs):
        super(UpdateCategoryForm, self).__init__(*args, **kwargs)
        self.id = blog_category_id

    def validate_category(self, field):
        if BlogCategory.query.filter_by(category=field.data).first():
            raise ValidationError('入力されたカテゴリ名は既に使われています。')

class BlogPostForm(FlaskForm):
    title = StringField('タイトル', validators=[DataRequired()])
    category = SelectField('カテゴリ', coerce=int, validators=[DataRequired()])
    summary = StringField('要約')  
    text = TextAreaField('本文', validators=[DataRequired()])
    picture = FileField('アイキャッチ画像', validators=[FileAllowed(['jpg', 'png', 'jpeg', 'gif'])])
    submit = SubmitField('投稿')

    def _set_category(self):
        try:
            blog_categories = BlogCategory.query.all()
            if blog_categories:
                self.category.choices = [(blog_category.id, blog_category.category) for blog_category in blog_categories]
                if not self.category.data:
                    self.category.data = blog_categories[0].id
            else:
                self.category.choices = []
        except Exception as e:
            print(f"カテゴリー取得エラー: {e}")
            self.category.choices = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_category()

class BlogSearchForm(FlaskForm):
    searchtext = StringField('検索テキスト', validators=[DataRequired()])
    submit = SubmitField('検索')

class InquiryForm(FlaskForm):
    name = StringField('お名前（必須）', validators=[DataRequired()])
    email = StringField('メールアドレス（必須）', validators=[DataRequired(), Email(message='正しいメールアドレスを入力してください')])
    title = StringField('題名')
    text = TextAreaField('メッセージ本文（必須）', validators=[DataRequired()])
    submit = SubmitField('送信')